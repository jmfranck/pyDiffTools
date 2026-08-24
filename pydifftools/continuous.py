"""Continuous Pandoc build utility that requires geckodriver."""

import time
import subprocess
import sys
import os
import errno
import re
import shutil
import threading
import queue
import traceback
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from .command_registry import register_command
from .browser_lifecycle import (
    browser_window_is_alive,
    close_browser_window,
    forward_search_in_browser,
)
from .forward_search import (
    CPB_FORWARD_SEARCH_PORT,
    FORWARD_SEARCH_HOST,
    bind_forward_search_server,
    drain_forward_search_queue,
    serve_forward_search,
)

FORWARD_SEARCH_PORT = CPB_FORWARD_SEARCH_PORT
POLL_INTERVAL_SECONDS = 0.1
SOURCE_SETTLE_SECONDS = 0.25
MAIN_LOOP_INTERVAL_SECONDS = 0.05
MARGIN_COMMENTS_FILTER_MARKER = "-- PYDIFFTOOLS_SPECIAL_MARGIN_COMMENTS_FILTER"
NO_COMMENTS_FILTER_MARKER = (
    "-- PYDIFFTOOLS_SPECIAL_NO_COMMENTS_FILTER"
)


def _comment_filter_mode(path, packaged_filters=None):
    if not os.path.exists(path):
        return "missing"
    if packaged_filters is None:
        package_dir = os.path.dirname(os.path.abspath(__file__))
        packaged_filters = {
            "default": os.path.join(package_dir, "comment_tags.lua"),
            "margin": os.path.join(package_dir, "comment_tags_margin.lua"),
            "none": os.path.join(package_dir, "comment_tags_no_comments.lua"),
        }
    with open(path, encoding="utf-8") as fp:
        filter_text = fp.read()
    for mode in ["default", "margin", "none"]:
        with open(packaged_filters[mode], encoding="utf-8") as fp:
            if filter_text == fp.read():
                return mode
    return "custom"


def _confirm_restore_comment_filter(active_mode):
    if active_mode == "none":
        message = (
            "The current lua filter is the one that does not show comments, "
            "but you ran without the --no-comments flag.\n\n"
            "Note that you have not locally edited the filter relative to "
            "the library default.\n\n"
            "Do you want to show comments, or continue with no comments?"
        )
        default_choice = "restore"
    elif active_mode == "custom":
        message = (
            "The current lua filter does not match the pyDiffTools library "
            "default or the no-comments filter, but you ran without the "
            "--no-comments flag.\n\n"
            "Note that this looks like a locally edited filter.\n\n"
            "Do you want to show comments using the library default, or "
            "continue with no comments?"
        )
        default_choice = "keep"
    else:
        raise ValueError(
            "Comment filter restore prompt is only valid for custom or "
            f"no-comments filters, not {active_mode!r}"
        )
    prompt_script = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv[:1])
box = QMessageBox()
box.setWindowTitle("pydifft cpb")
box.setIcon(QMessageBox.Icon.Question)
box.setText(sys.argv[1])
keep_button = box.addButton(
    "no comments", QMessageBox.ButtonRole.RejectRole
)
restore_button = box.addButton(
    "show comments", QMessageBox.ButtonRole.AcceptRole
)
if sys.argv[2] == "restore":
    box.setDefaultButton(restore_button)
else:
    box.setDefaultButton(keep_button)
box.exec()
if box.clickedButton() is restore_button:
    sys.exit(0)
sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", prompt_script, message, default_choice],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    stderr = result.stderr.strip()
    if stderr:
        raise RuntimeError(f"pydifft cpb filter dialog failed: {stderr}")
    raise RuntimeError("pydifft cpb filter dialog failed.")


def run_pandoc(
    filename,
    html_file,
    comments_to_margin=False,
    no_comments=False,
    comment_filter_session=None,
):
    if comments_to_margin:
        comment_filter_mode = "margin"
    elif no_comments:
        comment_filter_mode = "none"
    else:
        comment_filter_mode = "default"
    # Pandoc and pandoc-crossref must be installed for HTML rendering.
    if shutil.which("pandoc") is None:
        raise RuntimeError(
            "Pandoc must be installed to render HTML output. Install pandoc"
            " so the 'pandoc' executable is available on your PATH."
        )
    if shutil.which("pandoc-crossref") is None:
        raise RuntimeError(
            "Pandoc-crossref must be installed to render HTML output. Install"
            " pandoc-crossref so the 'pandoc-crossref' executable is available"
            " on your PATH."
        )
    if os.path.exists("MathJax-3.1.2"):
        has_local_jax = True
    else:
        has_local_jax = False
        print("you don't have a local copy of mathjax.  You could get it with")
        print(
            "wget https://github.com/mathjax/MathJax/archive/"
            + "refs/tags/3.1.2.zip"
        )
        print("and then unzip")
    # Collect companion files from the markdown file's directory so cpb works
    # even when started from a different working directory.
    source_dir = os.path.dirname(os.path.abspath(filename))
    with open(filename, encoding="utf-8") as fp:
        markdown_text = fp.read()
    if (
        "<comment>" in markdown_text
        or "<comment-left>" in markdown_text
        or "<comment-right>" in markdown_text
        or "comment-right" in markdown_text
        or "comment-left" in markdown_text
    ):
        # Keep the active comment filter in the markdown directory so pandoc
        # picks it up alongside other user-supplied project filters.
        # {{{ select the active comment_tags.lua filter
        package_dir = os.path.dirname(os.path.abspath(__file__))
        active_filter = os.path.join(source_dir, "comment_tags.lua")
        inactive_filter = os.path.join(
            source_dir, "comment_tags.lua.inactive"
        )
        packaged_filters = {
            "default": os.path.join(package_dir, "comment_tags.lua"),
            "margin": os.path.join(package_dir, "comment_tags_margin.lua"),
            "none": os.path.join(package_dir, "comment_tags_no_comments.lua"),
        }
        active_mode = _comment_filter_mode(active_filter, packaged_filters)
        inactive_mode = _comment_filter_mode(inactive_filter, packaged_filters)

        if comment_filter_mode == "default":
            if active_mode == "default":
                effective_filter_mode = "default"
            elif active_mode in {"none", "custom"}:
                if (
                    comment_filter_session is not None
                    and "show_comments" in comment_filter_session
                ):
                    show_comments = comment_filter_session["show_comments"]
                else:
                    show_comments = _confirm_restore_comment_filter(
                        active_mode
                    )
                    if comment_filter_session is not None:
                        comment_filter_session["show_comments"] = (
                            show_comments
                        )
                if show_comments:
                    shutil.copy2(
                        packaged_filters["default"], active_filter
                    )
                    effective_filter_mode = "default"
                else:
                    effective_filter_mode = active_mode
            elif active_mode == "margin":
                if inactive_mode in {"default", "custom"}:
                    temp_filter = active_filter + ".swap_tmp"
                    os.replace(active_filter, temp_filter)
                    os.replace(inactive_filter, active_filter)
                    os.replace(temp_filter, inactive_filter)
                    effective_filter_mode = inactive_mode
                else:
                    os.replace(active_filter, inactive_filter)
                    shutil.copy2(
                        packaged_filters["default"], active_filter
                    )
                    effective_filter_mode = "default"
            elif active_mode == "missing":
                if inactive_mode in {"default", "custom"}:
                    os.replace(inactive_filter, active_filter)
                    effective_filter_mode = inactive_mode
                else:
                    shutil.copy2(
                        packaged_filters["default"], active_filter
                    )
                    effective_filter_mode = "default"
            else:
                shutil.copy2(packaged_filters["default"], active_filter)
                effective_filter_mode = "default"
        else:
            effective_filter_mode = comment_filter_mode
            if active_mode == comment_filter_mode:
                pass
            elif active_mode in {"default", "custom"}:
                os.replace(active_filter, inactive_filter)
                shutil.copy2(
                    packaged_filters[comment_filter_mode], active_filter
                )
            else:
                if active_mode == "missing" and inactive_mode not in {
                    "default",
                    "custom",
                }:
                    shutil.copy2(
                        packaged_filters["default"], inactive_filter
                    )
                shutil.copy2(
                    packaged_filters[comment_filter_mode], active_filter
                )
        # }}}
        # Only copy the comment UI assets when comments should be rendered.
        if effective_filter_mode != "none":
            for asset_name in ["comments.css", "comment_toggle.js"]:
                target_path = os.path.join(source_dir, asset_name)
                if not os.path.exists(target_path):
                    shutil.copy2(
                        os.path.join(package_dir, asset_name),
                        target_path,
                    )
    localfiles = {}
    for k in ["csl", "bib"]:
        localfiles[k] = [
            f for f in os.listdir(source_dir) if f.endswith("." + k)
        ]
        if len(localfiles[k]) == 1:
            localfiles[k] = os.path.join(source_dir, localfiles[k][0])
        elif len(localfiles[k]) == 0:
            localfiles[k] = None
        else:
            raise ValueError(
                f"You have more than one {k} file in this directory!"
                " Get rid of all but one! of " + "and".join(localfiles[k])
            )
    # Include any css files next to the markdown source in the pandoc output.
    localfiles["css"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".css")]
    )
    # Include any lua filters next to the markdown source in the pandoc
    # output by passing repeated --lua-filter arguments.
    lua_priority = {
        "scholarly-metadata.lua": 0,
        "author-info-blocks.lua": 1,
    }
    localfiles["lua"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".lua")],
        key=lambda name: (lua_priority.get(name, 2), name),
    )
    # Include any javascript files next to the markdown source by injecting
    # script tags after pandoc runs. This adds extra javascript and does not
    # replace pandoc's own MathJax script configuration.
    localfiles["js"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".js")]
    )
    command = [
        "pandoc",
        "--filter",
        "pandoc-crossref",
        "--citeproc",
        "--mathjax",
        "--number-sections",
        "--toc",
        "-s",
        "-o",
        html_file,
        filename,
    ]
    if localfiles["bib"]:
        command[1:1] = ["--bibliography", localfiles["bib"]]
    if localfiles["csl"]:
        command.insert(1, f"--csl={localfiles['csl']}")
    for css_file in localfiles["css"]:
        command.extend(["--css", os.path.join(source_dir, css_file)])
    for lua_file in localfiles["lua"]:
        command.extend(["--lua-filter", os.path.join(source_dir, lua_file)])
    # command = ['pandoc', '-s', '--mathjax', '-o', html_file, filename]
    print("running:", " ".join(command))
    completed = subprocess.run(
        command,
    )
    if getattr(completed, "returncode", 0) != 0:
        raise RuntimeError(
            f"Pandoc failed with exit code {completed.returncode} while "
            f"building {html_file}.\n"
            f"Command: {' '.join(command)}"
        )
    print("running:\n", command)
    if not os.path.exists(html_file):
        raise RuntimeError(
            "Pandoc completed but did not create the expected HTML file: "
            f"{html_file}"
        )
    if has_local_jax:
        # {{{ for slow internet connection, remove remote files
        with open(html_file, encoding="utf-8") as fp:
            text = fp.read()
        patterns = [
            r"<script.{0,20}?cdn\.jsdeli.{0,20}?mathjax.{0,60}?script>",
            r"<script.{0,20}?https...polyfill.{0,60}?script>",
        ]
        for j in patterns:
            text = re.sub(j, "", text, flags=re.DOTALL)
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write(text)
        # }}}
    with open(html_file, encoding="utf-8") as fp:
        text = fp.read()
    html_was_updated = False
    if localfiles["js"]:
        script_block = ""
        for js_file in localfiles["js"]:
            script_block += (
                '\n<script src="'
                + os.path.join(source_dir, js_file)
                + '"></script>\n'
            )
        if script_block not in text:
            if "</head>" in text:
                text = text.replace("</head>", script_block + "</head>", 1)
            else:
                text = script_block + text
            html_was_updated = True
    style_block = (
        '\n<style id="pydifftools-hide-low-headers">\n'
        "h5, h6 { display: none; }\n"
        "</style>\n"
    )
    if style_block not in text:
        # hide organizational headers while keeping higher levels visible
        if "</head>" in text:
            text = text.replace("</head>", style_block + "</head>", 1)
        else:
            text = style_block + text
        html_was_updated = True
    if html_was_updated:
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write(text)
    return


def append_autorefresh(html_file):
    with open(html_file, "r", encoding="utf-8") as fp:
        all_data = fp.read()
    all_data = all_data.replace(
        "</head>",
        """
    <script id="MathJax-script" async src="MathJax-3.1.2/es5/tex-mml-chtml.js"\
></script>
    <script>
        var commentBubbleSelector =
            "div.comment-left, div.comment-right, " +
            "span.comment-pin > span.comment-left, " +
            "span.comment-pin > span.comment-right, " +
            ".comment-overlay.comment-left, " +
            ".comment-overlay.comment-right";

        // When the page is about to be unloaded, save the current scroll\
position
        window.addEventListener('beforeunload', function() {
            sessionStorage.setItem('scrollPosition', window.scrollY);
            var hiddenCommentIndexes = [];
            var bubbles = document.querySelectorAll(commentBubbleSelector);
            bubbles.forEach(function(bubble, index) {
                if (bubble.classList.contains('comment-hidden')) {
                    hiddenCommentIndexes.push(index);
                }
            });
            sessionStorage.setItem(
                'commentHiddenBubbleIndexes',
                JSON.stringify(hiddenCommentIndexes)
            );
        });

        // When the page has loaded,
        // restore hidden comments and scroll position
        window.addEventListener('load', function() {
            var hiddenCommentIndexes = sessionStorage.getItem(
                'commentHiddenBubbleIndexes'
            );
            if (hiddenCommentIndexes) {
                try {
                    var hiddenIndexes = JSON.parse(hiddenCommentIndexes);
                    var bubbles = document.querySelectorAll(
                        commentBubbleSelector
                    );
                    hiddenIndexes.forEach(function(index) {
                        if (bubbles[index]) {
                            bubbles[index].classList.add('comment-hidden');
                        }
                    });
                } catch (_error) {
                    // Ignore malformed session state and continue loading.
                }
                sessionStorage.removeItem('commentHiddenBubbleIndexes');
            }
            var scrollPosition = sessionStorage.getItem('scrollPosition');
            if (scrollPosition) {
                window.scrollTo(0, scrollPosition);
                sessionStorage.removeItem('scrollPosition');
            }
        });
    </script>
</head>
    """,
    )
    with open(html_file, "w", encoding="utf-8") as fp:
        fp.write(all_data)


class Handler(FileSystemEventHandler):
    """Queue source changes without doing build or browser work."""

    def __init__(self, filename, change_queue):
        self.filename = os.path.normpath(os.path.abspath(filename))
        self.change_queue = change_queue

    def _queue_if_source_changed(self, *paths):
        if self.filename not in {
            os.path.normpath(os.path.abspath(path)) for path in paths if path
        }:
            return
        self.change_queue.put_nowait(None)

    def on_modified(self, event):
        if not event.is_directory:
            self._queue_if_source_changed(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._queue_if_source_changed(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._queue_if_source_changed(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._queue_if_source_changed(event.src_path, event.dest_path)


@register_command(
    "continuous pandoc build.  Like latexmk, but for markdown!",
    help={
        "filename": "Markdown or TeX file to watch for changes",
        "comments_to_margin": (
            "Temporarily replace comment_tags.lua with the special margin "
            "comments filter for printing."
        ),
        "no_comments": (
            "Render the HTML without comment tags or comment div blocks."
        ),
    },
    filename_extensions={"filename": ".md"},
)
def cpb(filename, comments_to_margin=False, no_comments=False):
    source_path = os.path.normpath(os.path.abspath(filename))
    source_dir = os.path.dirname(source_path)
    html_file = filename.rsplit(".", 1)[0] + ".html"
    comment_filter_session = {}
    search_queue = queue.Queue()
    stop_event = threading.Event()
    forward_search_server = bind_forward_search_server(
        (FORWARD_SEARCH_HOST, FORWARD_SEARCH_PORT), "cpb"
    )
    socket_thread = threading.Thread(
        target=serve_forward_search,
        args=(forward_search_server, stop_event, search_queue),
        daemon=True,
    )
    chrome = None
    observer = None
    observer_started = False
    socket_thread_started = False

    try:
        # Bind and serve before any build or browser work. This makes the fixed
        # port authoritative even while a slow initial build is in progress.
        socket_thread.start()
        socket_thread_started = True

        # Build before opening Chrome so a failed initial build cannot leave an
        # orphaned browser session. Remember the source version from before
        # the build so an edit during a slow Pandoc run remains pending.
        source_missing = object()
        initial_source_stat = os.stat(source_path)
        handled_signature = (
            initial_source_stat.st_ino,
            initial_source_stat.st_size,
            initial_source_stat.st_mtime_ns,
        )
        run_pandoc(
            filename,
            html_file,
            comments_to_margin=comments_to_margin,
            no_comments=no_comments,
            comment_filter_session=comment_filter_session,
        )
        append_autorefresh(html_file)

        # Selenium is deliberately initialized once, after the first
        # successful build. Nothing in recovery constructs a browser.
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException

        chrome = webdriver.Chrome()
        observer = Observer()
        change_queue = queue.Queue()
        event_handler = Handler(filename, change_queue)
        # {{{ fall back when the system cannot allocate an inotify watcher
        observer.schedule(event_handler, path=source_dir, recursive=False)
        try:
            observer.start()
        except OSError as exc:
            if exc.errno not in {errno.EMFILE, errno.ENOSPC}:
                raise
            observer.stop()
            print(
                "pydifft cpb: inotify resources are exhausted; falling "
                "back to polling for file changes.",
                file=sys.stderr,
            )
            observer = PollingObserver(timeout=POLL_INTERVAL_SECONDS)
            observer.schedule(event_handler, path=source_dir, recursive=False)
            observer.start()
            # PollingObserver.start() does not wait for its emitter's initial
            # directory snapshot. Do that before exposing Chrome, otherwise
            # the first user save can become the baseline and emit no event.
            snapshot_deadline = time.monotonic() + 1.0
            while any(
                getattr(emitter, "_snapshot", None) is None
                for emitter in observer.emitters
            ):
                if not observer.is_alive():
                    raise RuntimeError(
                        "The polling file watcher stopped before its initial "
                        "snapshot completed."
                    )
                if time.monotonic() >= snapshot_deadline:
                    raise RuntimeError(
                        "The polling file watcher did not establish its "
                        "initial snapshot."
                    )
                time.sleep(MAIN_LOOP_INTERVAL_SECONDS)
        observer_started = True
        # }}}
        # Do not expose the preview until watching is active. Otherwise a save
        # immediately after Chrome loads can become polling's initial snapshot
        # and never be reported as a change.
        chrome.get("file://" + os.path.abspath(html_file))
        rebuild_pending = False
        stable_signature = None
        stable_since = None
        while True:
            if not socket_thread.is_alive():
                raise RuntimeError(
                    "The cpb forward-search listener stopped unexpectedly; "
                    "closing the preview instead of leaving an "
                    "undiscoverable session."
                )
            # Chrome closure is terminal. Source-file and build failures do
            # not affect browser ownership or observer lifetime.
            if not browser_window_is_alive(chrome):
                break

            for queued_search in drain_forward_search_queue(search_queue):
                search_text = queued_search.strip()
                if search_text:
                    forward_search_in_browser(chrome, search_text)

            saw_source_event = False
            while not change_queue.empty():
                change_queue.get_nowait()
                saw_source_event = True
            if saw_source_event:
                rebuild_pending = True
                stable_signature = None
                stable_since = None

            # PollingEmitter establishes its first snapshot asynchronously.
            # Compare against the last handled source signature as a backstop
            # so an edit in that narrow startup window cannot disappear into
            # the initial snapshot without generating an event.
            if not rebuild_pending:
                try:
                    current_source_stat = os.stat(source_path)
                except FileNotFoundError:
                    current_source_signature = source_missing
                else:
                    current_source_signature = (
                        current_source_stat.st_ino,
                        current_source_stat.st_size,
                        current_source_stat.st_mtime_ns,
                    )
                if current_source_signature != handled_signature:
                    rebuild_pending = True
                    stable_signature = None
                    stable_since = None

            # {{{ wait for an editor save to restore and settle the source
            if rebuild_pending:
                now = time.monotonic()
                try:
                    source_stat = os.stat(source_path)
                except FileNotFoundError:
                    stable_signature = None
                    stable_since = None
                else:
                    current_signature = (
                        source_stat.st_ino,
                        source_stat.st_size,
                        source_stat.st_mtime_ns,
                    )
                    if current_signature != stable_signature:
                        stable_signature = current_signature
                        stable_since = now
                    elif now - stable_since >= SOURCE_SETTLE_SECONDS:
                        attempted_signature = stable_signature
                        rebuild_pending = False
                        stable_signature = None
                        stable_since = None
                        if not browser_window_is_alive(chrome):
                            break
                        try:
                            run_pandoc(
                                filename,
                                html_file,
                                comments_to_margin=comments_to_margin,
                                no_comments=no_comments,
                                comment_filter_session=comment_filter_session,
                            )
                            append_autorefresh(html_file)
                        except Exception as exc:
                            exception_filename = getattr(exc, "filename", None)
                            missing_source = isinstance(
                                exc, FileNotFoundError
                            ) and (
                                not os.path.exists(source_path)
                                or (
                                    exception_filename
                                    and os.path.normpath(
                                        os.path.abspath(exception_filename)
                                    )
                                    == source_path
                                )
                            )
                            if missing_source:
                                rebuild_pending = True
                            else:
                                handled_signature = attempted_signature
                                print(
                                    "pydifft cpb: rebuild failed; keeping "
                                    "the current preview open.",
                                    file=sys.stderr,
                                )
                                traceback.print_exc()
                        else:
                            handled_signature = attempted_signature
                            if not browser_window_is_alive(chrome):
                                break
                            try:
                                chrome.refresh()
                            except WebDriverException:
                                print(
                                    "pydifft cpb: Chrome is no longer "
                                    "available; stopping without reopening "
                                    "it.",
                                    file=sys.stderr,
                                )
                                break
            # }}}
            time.sleep(MAIN_LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        forward_search_server.close()
        if observer_started:
            observer.stop()
            observer.join()
        if socket_thread_started:
            socket_thread.join()
        close_browser_window(chrome)


if __name__ == "__main__":
    raise SystemExit("Use `pydifft cpb <filename.md>` instead.")
