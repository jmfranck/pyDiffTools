"""Continuous Pandoc build utility with a Selenium browser preview."""

import json
import hashlib
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
import tempfile
from pathlib import Path
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from .command_registry import register_command
from .wrapping_options import (
    DEFAULT_WIDTH, DEFAULT_TRAILING_DEPENDENT_PHRASE, WRAPPING_ARGUMENTS,
)
from .zotero import recover_bibliography, zotero_notice
from .comment_migration import prepare_comment_source
from .browser_lifecycle import (
    browser_window_is_alive,
    close_browser_window,
    dialog_callbacks,
    forward_search_in_browser,
    prepare_for_dialog,
    start_browser,
)
from .forward_search import (
    CPB_FORWARD_SEARCH_PORT,
    FORWARD_SEARCH_HOST,
    bind_forward_search_server,
    drain_forward_search_queue,
    serve_forward_search,
)
from .source_jump import SourceJumpServer

FORWARD_SEARCH_PORT = CPB_FORWARD_SEARCH_PORT
POLL_INTERVAL_SECONDS = 0.1
SOURCE_SETTLE_SECONDS = 0.25
MAIN_LOOP_INTERVAL_SECONDS = 0.05
MARGIN_COMMENTS_FILTER_MARKER = "-- PYDIFFTOOLS_SPECIAL_MARGIN_COMMENTS_FILTER"
NO_COMMENTS_FILTER_MARKER = (
    "-- PYDIFFTOOLS_SPECIAL_NO_COMMENTS_FILTER"
)


def _comment_filter_digest(path):
    # Normalize line endings so a Windows checkout is still a known version.
    content = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(
        b"\r", b"\n"
    )
    return hashlib.sha256(content).hexdigest()


def _comment_filter_git(source_dir, *args):
    """Run Git for managed filters without requiring a repository."""
    command = ["git", "-C", str(source_dir), *args]
    try:
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        ) as process:
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 1, "", "Git not installed")


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
    digest = _comment_filter_digest(path)
    for mode in ["default", "margin", "none"]:
        if digest == _comment_filter_digest(packaged_filters[mode]):
            return mode
    history_path = Path(__file__).with_name("comment_filter_history.json")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    if digest in history["comment_tags.lua"]:
        mode = history["comment_tags.lua"][digest]["mode"]
        return "outdated" if mode == "default" else "outdated-" + mode
    return "custom"


# Kept separate so its prompt choices can be unit-tested.
# also used by: tests/test_wrap_check.py and tests/cli/test_commands.py,
# which call it directly or monkeypatch it to answer the prompt (cpb calls
# it from run_pandoc)
def confirm_restore_comment_filter(active_mode):
    if active_mode == "none":
        message = (
            "The current lua filter is the one that does not show comments, "
            "but you ran without the --no-comments flag.\n\n"
            "Its hash matches a current or historical distributed "
            "no-comment filter.\n\n"
            "Do you want to update the filter and comment styles to the "
            "library versions and show comments, or keep no comments? "
            "Updating also untracks the generated helpers and ignores "
            "them in Git."
        )
        default_choice = "restore"
        update_label = "update filter and styles; show comments"
        keep_label = "keep no comments"
    elif active_mode == "custom":
        message = (
            "One or more comment helper files (Lua, CSS or JavaScript) "
            "do not match any current or historical package version. "
            "They appear to be locally modified.\n\n"
            "Update the helpers to the library versions for the selected "
            "comment mode, or keep the current files?"
        )
        default_choice = "restore"
        update_label = "update filter and styles; untrack and ignore"
        keep_label = "keep current helper files"
    elif active_mode == "outdated":
        message = (
            "One or more comment helpers match known older versions "
            "from the pyDiffTools Git history. Updating is recommended "
            "to get the current comment-tag behavior and fixes.\n\n"
            "Replace it and the comment styles with the library versions?"
        )
        default_choice = "restore"
        update_label = "update filter and styles; untrack and ignore"
        keep_label = "keep older helpers for this session"
    elif active_mode == "tracked":
        message = (
            "Comment helper files are tracked by Git. These generated "
            "files should normally be managed by pyDiffTools.\n\n"
            "The recommended choice removes it from Git tracking, adds "
            "it to .gitignore, and uses the current library version. "
            "The working copy stays on disk."
        )
        default_choice = "restore"
        update_label = "let pyDiffTools manage; untrack and ignore"
        keep_label = "keep current helpers tracked by Git"
    else:
        raise ValueError(
            "Comment filter restore prompt is only valid for custom, "
            f"outdated, tracked or no-comments filters, not {active_mode!r}"
        )
    if active_mode in {"custom", "outdated"}:
        message += (
            "\n\nIf it is tracked by Git, updating also removes it from "
            "tracking and adds it to .gitignore."
        )
    prompt_script = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv[:1])
box = QMessageBox()
box.setWindowTitle("pydifft cpb")
box.setIcon(QMessageBox.Icon.Question)
box.setText(sys.argv[1])
keep_button = box.addButton(sys.argv[3], QMessageBox.ButtonRole.ActionRole)
restore_button = box.addButton(sys.argv[4], QMessageBox.ButtonRole.AcceptRole)
cancel_button = box.addButton("cancel", QMessageBox.ButtonRole.RejectRole)
box.setEscapeButton(cancel_button)
if sys.argv[2] == "restore":
    box.setDefaultButton(restore_button)
else:
    box.setDefaultButton(keep_button)
while True:
    box.exec()
    if box.clickedButton() is restore_button:
        sys.exit(0)
    if box.clickedButton() is not keep_button:
        sys.exit(2)
    if sys.argv[5] == "none":
        sys.exit(1)
    confirmation = QMessageBox()
    confirmation.setWindowTitle("Keep this comment filter?")
    confirmation.setIcon(QMessageBox.Icon.Warning)
    confirmation.setText(
        "Are you really sure you want to keep this filter instead of "
        "letting pyDiffTools manage it? It may lack current comment-tag "
        "fixes. If it is tracked by Git, it will remain tracked.\\n\\n"
        "For local modifications or a current tracked filter, approval "
        "is recorded in .pydifft-comment-filter.json beside your source "
        "file. You will be asked again if any helper changes. Known older "
        "versions are kept only for this session."
    )
    go_back = confirmation.addButton(
        "go back", QMessageBox.ButtonRole.RejectRole
    )
    keep_local = confirmation.addButton(
        ("keep older helpers for this session" if sys.argv[5] == "outdated"
         else "keep local helpers and stop asking"),
        QMessageBox.ButtonRole.AcceptRole
    )
    confirmation.setDefaultButton(go_back)
    confirmation.exec()
    if confirmation.clickedButton() is keep_local:
        sys.exit(1)
"""
    prepare_for_dialog()
    result = subprocess.run(
        [
            sys.executable, "-c", prompt_script, message, default_choice,
            keep_label, update_label, active_mode,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    if result.returncode == 2:
        return None
    stderr = result.stderr.strip()
    if stderr:
        raise RuntimeError(f"pydifft cpb filter dialog failed: {stderr}")
    raise RuntimeError("pydifft cpb filter dialog failed.")


# also used by: tests/test_wrap_check.py, which drives this window directly
# (cpb calls it from run_pandoc)
def show_markdown_fix_dialog(report):
    """Show automatic fixes and any source edits that still need a user."""
    from html import escape

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
    )

    fixes = report["fixes"]
    warnings = report["warnings"]
    if not fixes and not warnings:
        return
    prepare_for_dialog()

    # a QApplication must exist before any widget is constructed
    application = QApplication.instance() or QApplication([])
    dialog = QDialog()
    dialog._pydifftools_application = application
    dialog.setWindowTitle("Markdown source fixes")
    fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    def annotated_source(before, after, line):
        """Mark changed breaks on their positions in the original source."""
        original_words = list(re.finditer(r"\S+", before))
        updated_words = list(re.finditer(r"\S+", after))
        if [word[0] for word in original_words] != [
            word[0] for word in updated_words
        ]:
            return None
        marks = {}
        for number in range(len(original_words) + 1):
            start = original_words[number - 1].end() if number else 0
            stop = (
                original_words[number].start()
                if number < len(original_words)
                else len(before)
            )
            updated_start = updated_words[number - 1].end() if number else 0
            updated_stop = (
                updated_words[number].start()
                if number < len(updated_words)
                else len(after)
            )
            old_breaks = [
                start + match.start()
                for match in re.finditer("\n", before[start:stop])
            ]
            new_count = after[updated_start:updated_stop].count("\n")
            if new_count > len(old_breaks):
                marks[start] = (
                    "<span style='color:#188038; font-weight:bold'>↳</span>"
                    * (new_count - len(old_breaks))
                )
            for position in old_breaks[new_count:]:
                marks[position] = (
                    "<span style='color:#c62828; font-weight:bold'>↳×</span>"
                )
        if not marks:
            return None
        marked = "".join(
            marks.get(position, "") + escape(char)
            for position, char in enumerate(before)
        ) + marks.get(len(before), "")
        return "<br>".join(
            f"<span style='color:#666'>{line + offset:>6}</span> " + value
            for offset, value in enumerate(marked.split("\n"))
        )

    screen_height = dialog.screen().availableGeometry().height()
    dialog.resize(900, int(screen_height * 0.85))
    layout = QVBoxLayout(dialog)
    heading = QLabel()
    heading.setWordWrap(True)
    details = QLabel()
    details.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(details)

    preview_row = QHBoxLayout()
    line_numbers = QLabel()
    line_numbers.setAlignment(
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
    )
    line_numbers.setStyleSheet("color: #666; padding-right: 8px;")
    line_numbers.setFont(fixed_font)
    preview = QTextEdit()
    preview.setReadOnly(True)
    preview.setFont(fixed_font)
    preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
    preview_row.addWidget(line_numbers)
    preview_row.addWidget(preview, 1)
    layout.addLayout(preview_row, 1)

    button = QPushButton()
    layout.addWidget(button)

    def render_fix_page(page_fixes, reason, page=""):
        count = len(page_fixes)
        heading.setText(
            "I fixed this source hunk automatically." + page
            if count == 1
            else f"I fixed these {count} source hunks automatically." + page
        )
        details.setText(
            reason
            + (
                "<br>Original source: "
                "<span style='color:#188038'>↳</span> inserted newline; "
                "<span style='color:#c62828'>↳×</span> removed newline."
                if any(fix["annotated"] for fix in page_fixes) else ""
            )
        )
        line_numbers.setVisible(False)
        preview.setHtml(
            "<pre style='font-family:monospace; margin:0'>"
            + "<br><br>".join(fix["preview"] for fix in page_fixes)
            + "</pre>"
        )

    # {{{ render hunks once and pack each page to the actual viewport height
    groups = {}
    for fix in fixes:
        annotated = annotated_source(fix["before"], fix["after"], fix["line"])
        entry = annotated
        if entry is None:
            rows = []
            for offset, value in enumerate(fix["before"].splitlines() or [""]):
                stripped = value.rstrip(" ")
                rows.append(
                    f"<span style='color:#666'>{fix['line'] + offset:>6}"
                    "</span> − " + escape(stripped)
                    + "<span style='background:#fbb'>·</span>"
                    * (len(value) - len(stripped))
                )
            for offset, value in enumerate(
                [] if fix["after"] == fix["before"].rstrip()
                else fix["after"].split("\n")
            ):
                rows.append(
                    f"<span style='color:#666'>{fix['line'] + offset:>6}"
                    "</span> " + ("+ " if offset == 0 else "↳ ")
                    + escape(value)
                )
            entry = "<br>".join(rows)
        groups.setdefault(fix["reason"], []).append({
            **fix, "preview": entry, "annotated": annotated is not None,
        })
    records = []
    button.setText("Next")
    dialog.ensurePolished()
    for reason, group in groups.items():
        page = []
        for fix in sorted(group, key=lambda fix: fix["line"]):
            candidate = page + [fix]
            render_fix_page(candidate, reason, " (page 999 of 999)")
            layout.activate()
            if page and (
                preview.document().size().height()
                > preview.viewport().height()
            ):
                records.append({
                    "record_type": "fix", "reason": reason, "fixes": page,
                })
                page = [fix]
            else:
                page = candidate
        records.append({
            "record_type": "fix", "reason": reason, "fixes": page,
        })
    records += [
        {"record_type": "warning", **warning} for warning in warnings
    ]
    # }}}
    index = 0
    user_says_fixed = False

    def show_record():
        record = records[index]
        page = (
            f" (page {index + 1} of {len(records)})"
            if len(records) > 1
            else ""
        )
        if record["record_type"] == "fix":
            render_fix_page(record["fixes"], record["reason"], page)
            button.setText("Next" if index + 1 < len(records) else "Done")
        else:
            line = record["line"]
            heading.setText("This source span is not closed." + page)
            line_numbers.setVisible(True)
            if record["kind"] == "math":
                delimiter = record["delimiter"]
                details.setText(
                    f"This math has no closing {delimiter}. Add {delimiter} "
                    "where the expression ends, then choose “I've fixed it”."
                )
            else:
                details.setText(
                    "This HTML comment has no closing -->. Add --> where "
                    "the comment ends, then choose “I've fixed it”."
                )
            offending_lines = record["offending"].splitlines() or [""]
            line_numbers.setText(
                "<br>".join(
                    str(number)
                    for number in range(line, line + len(offending_lines))
                )
            )
            preview.setHtml(
                "<pre style='font-family:monospace; margin:0'><b>"
                + "<br>".join(escape(value) for value in offending_lines)
                + "</b></pre>"
            )
            button.setText("I've fixed it")

    def advance():
        nonlocal index, user_says_fixed
        if records[index]["record_type"] == "warning":
            user_says_fixed = True
            dialog.accept()
            return
        if index + 1 < len(records):
            index += 1
            show_record()
        else:
            dialog.accept()

    button.clicked.connect(advance)
    show_record()
    dialog.exec()
    return user_says_fixed


# also used by: tests/test_wrap_check.py, which drives this window directly
# (cpb calls it from run_pandoc)
def show_markdown_reload_dialog():
    """Ask the user to reload a source file changed by automatic fixes."""
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QPushButton,
        QVBoxLayout,
    )

    prepare_for_dialog()
    # a QApplication must exist before any widget is constructed
    application = QApplication.instance() or QApplication([])
    dialog = QDialog()
    dialog._pydifftools_application = application
    dialog.setWindowTitle("Reload the Markdown source")
    dialog.resize(440, 150)
    layout = QVBoxLayout(dialog)
    message = QLabel(
        "I fixed the Markdown source. Reload it in your editor to see the "
        "changes."
    )
    message.setWordWrap(True)
    layout.addWidget(message)
    button = QPushButton("I've reloaded")
    button.clicked.connect(dialog.accept)
    layout.addWidget(button)
    dialog.exec()


def run_pandoc(
    filename,
    html_file,
    comments_to_margin=False,
    no_comments=False,
    comment_filter_session=None,
    wrapnumber=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
    diff=None,
):
    # {{{ automatically fix Markdown source and request edits for
    # unfinished spans
    from .wrap_sentences import autofix_markdown_file

    automatic_fixes_were_made = False
    while True:
        report = autofix_markdown_file(
            filename, wrapnumber=wrapnumber, git_index=True, git_ref=diff,
            punctuation_slop=trailing_dependent_phrase,
        )
        automatic_fixes_were_made |= bool(report["fixes"])
        if report["fixes"] or report["warnings"]:
            user_says_fixed = show_markdown_fix_dialog(report)
            if report["warnings"]:
                if not user_says_fixed:
                    raise RuntimeError(
                        "The Markdown source still has an unclosed math "
                        "expression or HTML comment."
                    )
                continue
        break

    if automatic_fixes_were_made:
        # a corrected comment tag (e.g. <XYcomm> -> <XYcom>) can name an
        # author with no XYcolor yet, so migrate comments again now rather
        # than on the next save
        prepare_comment_source(filename)
        show_markdown_reload_dialog()
    # }}}

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
    helper_names = [
        "comment_tags.lua", "comments.css", "comments_author_colors.css",
        "comment_toggle.js",
    ]
    selected_comment_filter = None
    if (
        any(
            os.path.exists(os.path.join(source_dir, name))
            for name in [*helper_names, "comment_tags.lua.inactive"]
        )
        or re.search(
            r"</?[A-Za-z]{2}com(?:-(?:left|right))?>",
            markdown_text,
            re.IGNORECASE,
        )
        or re.search(
            r"\.[A-Za-z]{2}com(?:-(?:left|right))?(?=[\s}])",
            markdown_text,
            re.IGNORECASE,
        )
        or "<comment>" in markdown_text
        or "<comment-left>" in markdown_text
        or "<comment-right>" in markdown_text
        or "comment-right" in markdown_text
        or "comment-left" in markdown_text
    ):
        # {{{ Manage one local filter, recognize history and approved edits
        package_dir = Path(__file__).resolve().parent
        local_filter = Path(source_dir) / "comment_tags.lua"
        legacy_filter = Path(source_dir) / "comment_tags.lua.inactive"
        approval_path = Path(source_dir) / ".pydifft-comment-filter.json"
        packaged_filters = {
            "default": package_dir / "comment_tags.lua",
            "margin": package_dir / "comment_tags_margin.lua",
            "none": package_dir / "comment_tags_no_comments.lua",
        }
        history = json.loads(
            (package_dir / "comment_filter_history.json").read_text(
                encoding="utf-8"
            )
        )
        known_modes = {
            digest: item["mode"]
            for digest, item in history["comment_tags.lua"].items()
        }
        known_modes.update({
            _comment_filter_digest(file): mode
            for mode, file in packaged_filters.items()
        })
        original_mode = _comment_filter_mode(local_filter, packaged_filters)
        legacy_mode = _comment_filter_mode(legacy_filter, packaged_filters)
        # Recover a user's normal filter from the former swap scheme once.
        if original_mode in {
            "missing", "margin", "none", "outdated-margin", "outdated-none",
        } and legacy_mode in {"default", "custom", "outdated"}:
            shutil.copy2(legacy_filter, local_filter)
        elif original_mode == "missing":
            shutil.copy2(packaged_filters["default"], local_filter)
        local_mode = _comment_filter_mode(local_filter, packaged_filters)
        local_digest = _comment_filter_digest(local_filter)
        helper_digests = {
            name: _comment_filter_digest(Path(source_dir) / name)
            for name in helper_names if (Path(source_dir) / name).exists()
        }
        try:
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            if not isinstance(approval, dict):
                approval = {}
        except (OSError, ValueError):
            approval = {}
        tracked = _comment_filter_git(
            source_dir, "ls-files", "-z", "--", *helper_names,
            "comment_tags.lua.inactive",
        )
        tracked_files = (
            tracked.stdout.rstrip("\0").split("\0")
            if tracked.returncode == 0 and tracked.stdout else []
        )
        keep_tracked = (
            any(name in tracked_files for name in helper_names)
            and approval.get("keep_tracked") is True
        )
        approved = (
            approval.get("files") == helper_digests
            and (not tracked_files or keep_tracked)
            and not local_mode.startswith("outdated")
        )
        effective_filter_mode = comment_filter_mode
        previous_mode = (
            "none" if original_mode.endswith("none") else local_mode
        )
        replace_styles = False
        if comment_filter_mode == "default" and previous_mode in {
            "none", "outdated-none",
        }:
            if (
                comment_filter_session is not None
                and comment_filter_session.get("no_comments_sha256")
                == local_digest
            ):
                show_comments = comment_filter_session["show_comments"]
            else:
                show_comments = confirm_restore_comment_filter("none")
                if show_comments is None:
                    raise RuntimeError("Comment filter selection cancelled.")
            if show_comments:
                replace_styles = True
                keep_tracked = False
            else:
                effective_filter_mode = "none"
        prompt_mode = None
        helper_states = [local_mode]
        for name, digest in helper_digests.items():
            if name == "comment_tags.lua":
                continue
            current = _comment_filter_digest(package_dir / name)
            helper_states.append(
                "current" if digest == current else
                "outdated" if digest in history[name] else "custom"
            )
        # Approvals cover the actual files, never a remembered rendering mode.
        approved &= not replace_styles and not any(
            state.startswith("outdated") for state in helper_states
        )
        keep_local = approved
        if not approved and not replace_styles:
            if "custom" in helper_states:
                prompt_mode = "custom"
            elif any(state.startswith("outdated") for state in helper_states):
                prompt_mode = "outdated"
            elif tracked_files:
                prompt_mode = "tracked"
        if prompt_mode is not None:
            if (
                comment_filter_session is not None
                and comment_filter_session.get("files") == helper_digests
            ):
                update = comment_filter_session["update_filter"]
            else:
                update = confirm_restore_comment_filter(prompt_mode)
                if update is None:
                    raise RuntimeError("Comment filter update cancelled.")
                if comment_filter_session is not None:
                    comment_filter_session.update(
                        files=helper_digests, update_filter=update,
                    )
            keep_local = not update
            keep_tracked = keep_local and any(
                name in tracked_files for name in helper_names
            )
            replace_styles |= update
        # Update the index only for the generated project copies, never other
        # Lua filters or the package's authoritative sources.
        untrack = [
            name for name in tracked_files
            if name == "comment_tags.lua.inactive" or not keep_tracked
        ]
        if untrack:
            result = _comment_filter_git(
                source_dir, "rm", "--cached", "--", *untrack
            )
            if result.returncode:
                raise RuntimeError(
                    "Cannot stop tracking the managed comment filter: "
                    + result.stderr.strip()
                )
            print("cpb: removed generated comment filters from Git tracking.")
        ignore_path = Path(source_dir) / ".gitignore"
        ignore_text = (
            ignore_path.read_text(encoding="utf-8")
            if ignore_path.exists() else ""
        )
        patterns = [
            "/comment_tags.lua.inactive", "/.pydifft-comment-filter.json",
            "/.pydifft-comment-filter-backup.*",
        ]
        if not keep_tracked:
            patterns.extend("/" + name for name in helper_names)
        additions = [
            p for p in patterns if p not in ignore_text.splitlines()
        ]
        if additions:
            if ignore_text and not ignore_text.endswith("\n"):
                ignore_text += "\n"
            ignore_path.write_text(
                ignore_text + "\n".join(additions) + "\n",
                encoding="utf-8",
            )
        if keep_local:
            local_render_mode = known_modes.get(local_digest, "default")
            selected_comment_filter = (
                local_filter if local_render_mode == effective_filter_mode
                else packaged_filters[effective_filter_mode]
            )
        else:
            desired_filter = packaged_filters[effective_filter_mode]
            if local_digest != _comment_filter_digest(desired_filter):
                shutil.copy2(desired_filter, local_filter)
            selected_comment_filter = local_filter
            approval_path.unlink(missing_ok=True)
        # Retire legacy swap files, retaining unique local edits as ignored
        # recovery copies rather than discarding them.
        if legacy_filter.exists():
            legacy_digest = _comment_filter_digest(legacy_filter)
            if (
                legacy_mode == "custom"
                and legacy_digest != _comment_filter_digest(local_filter)
            ):
                backup = Path(source_dir) / (
                    ".pydifft-comment-filter-backup." + legacy_digest
                )
                legacy_filter.replace(backup)
                print(f"cpb: preserved a former local filter in {backup}")
            else:
                legacy_filter.unlink()
        if comment_filter_session is not None:
            if effective_filter_mode == "none":
                comment_filter_session.update(
                    no_comments_sha256=_comment_filter_digest(
                        selected_comment_filter
                    ), show_comments=False,
                )
            else:
                comment_filter_session.pop("no_comments_sha256", None)
                comment_filter_session.pop("show_comments", None)
        for asset_name in helper_names[1:]:
            target_path = Path(source_dir) / asset_name
            if effective_filter_mode != "none" or target_path.exists():
                if not target_path.exists() or not keep_local:
                    shutil.copy2(package_dir / asset_name, target_path)
        final_digests = {
            name: _comment_filter_digest(Path(source_dir) / name)
            for name in helper_names if (Path(source_dir) / name).exists()
        }
        if (
            keep_local and prompt_mode is not None
            and comment_filter_session is not None
        ):
            comment_filter_session["files"] = final_digests
        if keep_local and not any(
            state.startswith("outdated") for state in helper_states
        ):
            approval_path.write_text(json.dumps({
                "files": final_digests,
                "keep_tracked": keep_tracked,
            }, indent=2) + "\n", encoding="utf-8")
        # }}}
    # {{{ select the declared bibliography before adjacent-file discovery
    bibliography_declared = False
    bibliography_paths = []
    front_matter = re.match(
        r"\A\ufeff?---[^\S\n]*\n(.*?)\n(?:---|\.\.\.)[^\S\n]*(?:\n|$)",
        markdown_text,
        flags=re.DOTALL,
    )
    if front_matter:
        try:
            metadata = yaml.safe_load(front_matter[1])
        except yaml.YAMLError:
            metadata = None  # Pandoc will report invalid document metadata.
        if isinstance(metadata, dict) and "bibliography" in metadata:
            bibliography_declared = True
            declared = metadata["bibliography"]
            if isinstance(declared, str):
                declared = [declared]
            if isinstance(declared, list) and all(
                isinstance(value, str) and value for value in declared
            ):
                bibliography_paths = [
                    value if "://" in value
                    else os.path.abspath(os.path.join(source_dir, value))
                    for value in declared
                ]
    # }}}
    localfiles = {}
    for k in ["csl", "bib"]:
        if k == "bib" and bibliography_declared:
            localfiles[k] = None
            continue
        localfiles[k] = [
            f for f in os.listdir(source_dir) if f.endswith("." + k)
        ]
        if len(localfiles[k]) == 1:
            localfiles[k] = os.path.join(source_dir, localfiles[k][0])
        elif len(localfiles[k]) == 0:
            localfiles[k] = None
        elif k == "bib":
            print(
                "cpb: multiple adjacent .bib files; declare a bibliography "
                "in the Markdown metadata to enable citation recovery.",
                file=sys.stderr,
            )
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
    if not bibliography_declared and localfiles["bib"]:
        bibliography_paths = [localfiles["bib"]]
    for bibliography_path in bibliography_paths:
        command[1:1] = ["--bibliography", bibliography_path]
    recovery_bibliography = (
        bibliography_paths[0]
        if len(bibliography_paths) == 1
        and "://" not in bibliography_paths[0]
        else None
    )
    if localfiles["csl"]:
        command.insert(1, f"--csl={localfiles['csl']}")
    for css_file in localfiles["css"]:
        command.extend(["--css", os.path.join(source_dir, css_file)])
    for lua_file in localfiles["lua"]:
        lua_path = os.path.join(source_dir, lua_file)
        if (
            lua_file == "comment_tags.lua"
            and selected_comment_filter is not None
        ):
            lua_path = str(selected_comment_filter)
        command.extend(["--lua-filter", lua_path])
    # {{{ render, recover missing citations, and rebuild at most once
    with tempfile.TemporaryDirectory(prefix="pydifft-citations-") as temp_dir:
        diagnostic_path = Path(temp_dir) / "pandoc.json"
        command.extend(["--log", str(diagnostic_path)])
        for attempt in range(2):
            diagnostic_path.write_text("[]", encoding="utf-8")
            print("running:", " ".join(command))
            completed = subprocess.run(command)
            if getattr(completed, "returncode", 0) != 0:
                raise RuntimeError(
                    f"Pandoc failed with exit code {completed.returncode} "
                    f"while building {html_file}.\n"
                    f"Command: {' '.join(command)}"
                )
            try:
                diagnostics = json.loads(
                    diagnostic_path.read_text(encoding="utf-8")
                )
                if not isinstance(diagnostics, list):
                    raise ValueError("expected a list of Pandoc diagnostics")
                missing = []
                for diagnostic in diagnostics:
                    if not isinstance(diagnostic, dict):
                        continue
                    if diagnostic.get("type") != "CiteprocWarning":
                        continue
                    message = diagnostic.get("message", "")
                    match = re.fullmatch(
                        r"citation (.+) not found", str(message)
                    )
                    if match and match[1] not in missing:
                        missing.append(match[1])
            except (OSError, ValueError) as exc:
                print(
                    f"cpb: cannot read citation diagnostics: {exc}",
                    file=sys.stderr,
                )
                break
            if not missing:
                break
            if attempt == 0 and recover_bibliography(
                recovery_bibliography, missing, source=filename
            ):
                continue
            print(
                f"cpb: unresolved citations: {', '.join(missing)}",
                file=sys.stderr,
            )
            break
    # }}}
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


def append_autorefresh(html_file, source_jump_url=None):
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
    if source_jump_url:
        all_data = re.sub(
            r'\s*<script id="pydifft-source-jump-config">.*?</script>'
            r'\s*<script id="pydifft-source-jump">.*?</script>',
            "",
            all_data,
            flags=re.DOTALL,
        )
        source_jump_js = (
            Path(__file__).parent / "flowchart" / "source_jump.js"
        ).read_text(encoding="utf-8")
        source_jump_scripts = (
            '<script id="pydifft-source-jump-config">'
            "window.pydifftSourceJumpEndpoint = "
            + json.dumps(source_jump_url)
            + ";</script>"
            '<script id="pydifft-source-jump">'
            + source_jump_js
            + "</script>"
        )
        all_data = all_data.replace(
            "</head>", source_jump_scripts + "</head>", 1
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


# also used by: command_line.main through the command registry, and the
# CPB runtime tests in tests/test_continuous_shutdown.py and test_zotero.py.
@register_command(
    "continuous pandoc build.  Like latexmk, but for markdown!",
    help={
        "filename": "Markdown or TeX file to watch for changes",
        "comments_to_margin": (
            "Use the margin-comments Lua filter for printing."
        ),
        "no_comments": (
            "Render the HTML without comment tags or comment div blocks."
        ),
        "diff": (
            "Diff-lint against this Git ref (branch, tag, or commit). "
            "Defaults to the index, matching git diff; use @ for HEAD."
        ),
    },
    filename_extensions={"filename": ".md"},
    argument_options={**WRAPPING_ARGUMENTS, "diff": {"metavar": "REF"}},
)
def cpb(
    filename, comments_to_margin=False, no_comments=False,
    wrapnumber=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
    diff=None,
):
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
    scroll_position = 0
    observer = None
    observer_started = False
    socket_thread_started = False
    source_jump_server = None

    try:
        # Bind and serve before any build or browser work. This makes the fixed
        # port authoritative even while a slow initial build is in progress.
        socket_thread.start()
        socket_thread_started = True

        # Build before opening the browser so a failed build cannot leave an
        # orphaned browser session. Remember the source version from before
        # the build so an edit during a slow Pandoc run remains pending.
        source_missing = object()
        # every dialog is dealt with (OK pressed) before Pandoc runs or
        # The browser opens
        zotero_notice()
        prepare_comment_source(filename)
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
            wrapnumber=wrapnumber,
            trailing_dependent_phrase=trailing_dependent_phrase,
            diff=diff,
        )
        source_jump_server = SourceJumpServer(source_path)
        source_jump_server.start()
        append_autorefresh(html_file, source_jump_server.url)

        # Selenium is deliberately initialized once, after the first
        # successful build. Nothing in recovery constructs a browser.
        from selenium.common.exceptions import WebDriverException

        chrome = start_browser()
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
            # directory snapshot. Do that before opening the browser, otherwise
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
        # after the browser loads can become polling's initial snapshot
        # and never be reported as a change.
        chrome.get("file://" + os.path.abspath(html_file))

        def close_for_dialog():
            # a rebuild needs the user, so close the preview while the
            # issues are dealt with; it reopens once the rebuild is done
            nonlocal chrome, scroll_position
            if chrome is not None:
                # sessionStorage does not survive quitting the browser.
                scroll_position = chrome.execute_script(
                    "return window.scrollY;"
                )
                close_browser_window(chrome)
                chrome = None

        dialog_callbacks.append(close_for_dialog)
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
            # Browser closure is terminal. Source-file and build failures do
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
                            prepare_comment_source(filename)
                            run_pandoc(
                                filename,
                                html_file,
                                comments_to_margin=comments_to_margin,
                                no_comments=no_comments,
                                comment_filter_session=comment_filter_session,
                                wrapnumber=wrapnumber,
                                trailing_dependent_phrase=(
                                    trailing_dependent_phrase
                                ),
                                diff=diff,
                            )
                            append_autorefresh(
                                html_file, source_jump_server.url
                            )
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
                            if chrome is not None:
                                if not browser_window_is_alive(chrome):
                                    break
                                try:
                                    chrome.refresh()
                                except WebDriverException:
                                    print(
                                        "pydifft cpb: Browser is no longer "
                                        "available; stopping without "
                                        "reopening it.",
                                        file=sys.stderr,
                                    )
                                    break
                        if chrome is None:
                            # {{{ reopen the preview a dialog closed
                            chrome = start_browser()
                            chrome.get(
                                "file://" + os.path.abspath(html_file)
                            )
                            chrome.execute_script(
                                "window.scrollTo(0, arguments[0]);",
                                scroll_position,
                            )
                            # }}}
            # }}}
            time.sleep(MAIN_LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        forward_search_server.close()
        if source_jump_server is not None:
            source_jump_server.stop()
        if observer_started:
            observer.stop()
            observer.join()
        if socket_thread_started:
            socket_thread.join()
        close_browser_window(chrome)
        dialog_callbacks.clear()


if __name__ == "__main__":
    raise SystemExit("Use `pydifft cpb <filename.md>` instead.")
