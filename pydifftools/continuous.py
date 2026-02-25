"""Continuous Pandoc build utility that requires geckodriver."""

import time
import subprocess
import sys
import os
import re
import shutil
import socket
import threading
import queue
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from .command_registry import register_command
from .browser_lifecycle import browser_window_is_alive, close_browser_window

FORWARD_SEARCH_HOST = "127.0.0.1"
FORWARD_SEARCH_PORT = 51235
MARGIN_COMMENTS_FILTER_MARKER = "-- PYDIFFTOOLS_SPECIAL_MARGIN_COMMENTS_FILTER"


def forward_search_listener(stop_event, search_queue):
    # Listen for markdown forward-search requests and queue them for cpb.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((FORWARD_SEARCH_HOST, FORWARD_SEARCH_PORT))
    server.listen(5)
    server.settimeout(1.0)
    while not stop_event.is_set():
        try:
            connection, _ = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        with connection:
            payload = b""
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                payload += chunk
        if payload:
            search_queue.put(payload.decode("utf-8"))
    server.close()


def _file_contains_text(path, text):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fp:
        return text in fp.read()


def _is_margin_comments_filter(path):
    return _file_contains_text(path, MARGIN_COMMENTS_FILTER_MARKER)


def _set_comment_filter_mode(source_dir, comments_to_margin):
    package_dir = os.path.dirname(os.path.abspath(__file__))
    active_filter = os.path.join(source_dir, "comment_tags.lua")
    inactive_filter = os.path.join(source_dir, "comment_tags.lua.inactive")
    packaged_default = os.path.join(package_dir, "comment_tags.lua")
    packaged_margin = os.path.join(package_dir, "comment_tags_margin.lua")

    active_is_margin = _is_margin_comments_filter(active_filter)
    inactive_is_margin = _is_margin_comments_filter(inactive_filter)

    if comments_to_margin:
        if active_is_margin:
            return
        if os.path.exists(active_filter):
            os.replace(active_filter, inactive_filter)
        shutil.copy2(packaged_margin, active_filter)
        return

    if active_is_margin:
        if os.path.exists(inactive_filter) and not inactive_is_margin:
            temp_filter = active_filter + ".swap_tmp"
            os.replace(active_filter, temp_filter)
            os.replace(inactive_filter, active_filter)
            os.replace(temp_filter, inactive_filter)
        else:
            os.replace(active_filter, inactive_filter)
            shutil.copy2(packaged_default, active_filter)
        return

    if not os.path.exists(active_filter):
        if os.path.exists(inactive_filter) and not inactive_is_margin:
            os.replace(inactive_filter, active_filter)
        else:
            shutil.copy2(packaged_default, active_filter)


def run_pandoc(filename, html_file, comments_to_margin=False):
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
    # If this markdown uses <comment> tags, copy the packaged comment assets
    # into the markdown directory before collecting css/lua/js companion files.
    with open(filename, encoding="utf-8") as fp:
        markdown_text = fp.read()
    if "<comment>" in markdown_text:
        package_dir = os.path.dirname(os.path.abspath(__file__))
        for asset_name in ["comments.css", "comment_toggle.js"]:
            target_path = os.path.join(source_dir, asset_name)
            if not os.path.exists(target_path):
                shutil.copy2(
                    os.path.join(package_dir, asset_name),
                    target_path,
                )
        _set_comment_filter_mode(source_dir, comments_to_margin)
    localfiles = {}
    for k in ["csl", "bib"]:
        localfiles[k] = [
            f for f in os.listdir(source_dir) if f.endswith("." + k)
        ]
        if len(localfiles[k]) == 1:
            localfiles[k] = os.path.join(source_dir, localfiles[k][0])
        else:
            raise ValueError(
                f"You have more than one (or no) {k} file in this directory!"
                " Get rid of all but one! of " + "and".join(localfiles[k])
            )
    # Include any css files next to the markdown source in the pandoc output.
    localfiles["css"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".css")]
    )
    # Include any lua filters next to the markdown source in the pandoc
    # output by passing repeated --lua-filter arguments.
    localfiles["lua"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".lua")]
    )
    # Include any javascript files next to the markdown source by injecting
    # script tags after pandoc runs. This adds extra javascript and does not
    # replace pandoc's own MathJax script configuration.
    localfiles["js"] = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".js")]
    )
    command = [
        "pandoc",
        "--bibliography",
        localfiles["bib"],
        f"--csl={localfiles['csl']}",
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
    for css_file in localfiles["css"]:
        command.extend(["--css", os.path.join(source_dir, css_file)])
    for lua_file in localfiles["lua"]:
        command.extend(["--lua-filter", os.path.join(source_dir, lua_file)])
    # command = ['pandoc', '-s', '--mathjax', '-o', html_file, filename]
    print("running:", " ".join(command))
    subprocess.run(
        command,
    )
    print("running:\n", command)
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


class Handler(FileSystemEventHandler):
    def __init__(self, filename, observer, comments_to_margin=False):
        self.observer = observer
        self.filename = filename
        self.comments_to_margin = comments_to_margin
        self.html_file = filename.rsplit(".", 1)[0] + ".html"
        self.init_firefox()

    def init_firefox(self):
        # apparently, selenium breaks stdin/out for tests, so it must be
        # imported here
        from selenium import webdriver

        self.firefox = webdriver.Chrome()
        run_pandoc(
            self.filename,
            self.html_file,
            comments_to_margin=self.comments_to_margin,
        )
        if not os.path.exists(self.html_file):
            print("html doesn't exist")
        self.append_autorefresh()
        self.firefox.get("file://" + os.path.abspath(self.html_file))

    def on_modified(self, event):
        from selenium.common.exceptions import WebDriverException

        if os.path.normpath(
            os.path.abspath(event.src_path)
        ) == os.path.normpath(os.path.abspath(self.filename)):
            run_pandoc(
                self.filename,
                self.html_file,
                comments_to_margin=self.comments_to_margin,
            )
            self.append_autorefresh()
            try:
                self.firefox.refresh()
            except WebDriverException:
                print(
                    "I'm quitting!! You probably suspended the computer, which"
                    " seems to freak selenium out.  Just restart"
                )
                self.firefox.quit()
                self.init_firefox()

    def append_autorefresh(self):
        with open(self.html_file, "r", encoding="utf-8") as fp:
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

        // When the page has loaded, restore hidden comments and scroll position
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
        with open(self.html_file, "w", encoding="utf-8") as fp:
            fp.write(all_data)

    def forward_search(self, search_text):
        # Use the browser's built-in window.find to locate the text.
        if not search_text:
            return
        found = self.firefox.execute_script(
            """
            var searchText = arguments[0];
            if (!window.find) {
                return false;
            }
            var didFind = window.find(searchText);
            if (didFind && window.getSelection) {
                var selection = window.getSelection();
                if (selection.rangeCount > 0) {
                    var rect = selection.getRangeAt(0).getBoundingClientRect();
                    window.scrollBy(0, rect.top - window.innerHeight / 3);
                }
            }
            return didFind;
            """,
            search_text,
        )
        if not found:
            print("forward search did not find text:", search_text)
        # Bring the browser window to the foreground in Linux window managers.
        if os.name == "posix" and shutil.which("wmctrl"):
            window_title = self.firefox.execute_script(
                "return document.title;"
            )
            if window_title:
                # Try common Chromium title forms used by desktop environments.
                for title_candidate in [
                    window_title,
                    window_title + " - Google Chrome",
                    window_title + " - Chromium",
                    window_title + " - Chrome",
                ]:
                    subprocess.run(
                        ["wmctrl", "-a", title_candidate],
                        check=False,
                    )


@register_command(
    "continuous pandoc build.  Like latexmk, but for markdown!",
    help={
        "filename": "Markdown or TeX file to watch for changes",
        "comments_to_margin": (
            "Temporarily replace comment_tags.lua with the special margin "
            "comments filter for printing."
        ),
    },
)
def cpb(filename, comments_to_margin=False):
    observer = Observer()
    event_handler = Handler(
        filename, observer, comments_to_margin=comments_to_margin
    )
    search_queue = queue.Queue()
    stop_event = threading.Event()
    socket_thread = threading.Thread(
        target=forward_search_listener,
        args=(stop_event, search_queue),
        daemon=True,
    )
    socket_thread.start()
    observer.schedule(event_handler, path=".", recursive=False)
    observer.start()

    try:
        while True:
            # Exit when the browser window is closed so cpb does not leave a
            # background process running after the user closes Chrome.
            if not browser_window_is_alive(event_handler.firefox):
                break
            time.sleep(1)
            while not search_queue.empty():
                search_text = search_queue.get().strip()
                if search_text:
                    event_handler.forward_search(search_text)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        observer.stop()
        observer.join()
        socket_thread.join()
        close_browser_window(event_handler.firefox)


if __name__ == "__main__":
    filename = sys.argv[1]
    cpb(filename)
    # Open the HTML file in the default web browser
