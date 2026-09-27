import subprocess

import pytest

from pydifftools.wrap_sentences import (
    apply_markdown_issue_fix,
    autofix_markdown_file,
    check_prose,
    markdown_lint_issues_from_text,
    wr,
    wrap_prose,
    wrchk,
)
from test_wrapping import TABLES


def test_wr_output_is_always_clean():
    prose = (
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    wrapped = wrap_prose(prose, 30)
    assert check_prose(wrapped, 30, 20) == []


def test_shorter_user_break_is_clean():
    # The user broke earlier than wr's own choice would -- always fine.
    text = (
        "This is some\n"
        "ordinary prose\n"
        "with quite a few words that\n"
        "need wrapping across several\n"
        "lines for a real test.\n"
    )
    assert check_prose(text, 30, 20) == []


def test_word_moved_to_next_line_is_clean():
    # wr would wrap this as "...prose\nwith quite a few words that\n"
    # "need wrapping.". Moving "that" down to the final line (breaking
    # one word earlier than wr would, with the rest still fitting) is a
    # legitimate user-added break.
    text = (
        "This is some ordinary prose\n"
        "with quite a few words\n"
        "that need wrapping.\n"
    )
    assert check_prose(text, 30, 20) == []


def test_overlong_line_is_flagged_with_line_number_and_word():
    text = (
        "This is some ordinary prose with quite a few words that\n"
        "need wrapping across several\n"
        "lines for a real test.\n"
    )
    issues = check_prose(text, 30, 20)
    assert len(issues) == 1
    line, message = issues[0]
    assert line == 1
    assert "with" in message
    assert "too long" in message


def test_sentence_ends_mid_line_is_flagged():
    text = "First sentence ends here. Second sentence starts right after.\n"
    issues = check_prose(text, 60, 20)
    assert len(issues) == 1
    line, message = issues[0]
    assert line == 1
    assert "mid-line" in message
    assert r"\ " in message


def test_backslash_space_abbreviation_is_not_flagged():
    text = "See etc.\\ more.\n"
    assert check_prose(text, 60, 20) == []


def test_plain_space_after_abbreviation_still_flagged():
    # Without the escape, the crude heuristic can't tell "etc." from a
    # real sentence end -- a known, pre-existing limitation shared with wr.
    text = "See etc. more things here.\n"
    issues = check_prose(text, 60, 20)
    assert len(issues) == 1


def test_markdown_autofix_inserts_soft_returns(tmp_path):
    path = tmp_path / "source.md"
    path.write_text(
        "This deliberately lengthy source line contains a collection of "
        "words that should wrap before the end.\n"
        "First sentence ends here. A second sentence begins on this line.\n"
    )

    report = autofix_markdown_file(path)

    fixed = path.read_text()
    assert report["fixes"]
    assert report["warnings"] == []
    assert markdown_lint_issues_from_text(fixed, wrapnumber=55) == []
    assert "First sentence ends here.\nA second sentence" in fixed
    assert any(
        "moved the next words" in item["reason"]
        for item in report["fixes"]
    )


def test_one_reported_long_line_is_fixed_at_the_suggested_word():
    source = "This is a deliberately overlong sentence with many words here.\n"
    line, message = markdown_lint_issues_from_text(source, 25)[0]

    fixed, before, after, reason = apply_markdown_issue_fix(
        source, line, message
    )

    assert before in source
    assert "\n" in after
    assert after in fixed
    assert "hard to read" in reason


def test_unclosed_math_is_reported_after_fifty_lines():
    short_math = "$$\n" + ("x = y\n" * 48)
    long_math = "$$\n" + ("x = y\n" * 49)

    assert not any(
        "unclosed math" in message
        for _line, message in markdown_lint_issues_from_text(short_math)
    )
    issues = markdown_lint_issues_from_text(long_math)
    assert (1, "unclosed math: add the matching '$$' to close it") in issues


def test_unclosed_html_comment_is_reported_at_end_of_file():
    content = "<!--\n" + ("comment text\n" * 220)

    issues = markdown_lint_issues_from_text(content)

    assert (1, "unclosed HTML comment: add '-->' to close it") in issues
    assert not markdown_lint_issues_from_text("<!-- valid -->\n")


def test_unclosed_markers_inside_code_are_ignored():
    content = (
        "Use `<!--` and `$` as literal examples.\n\n"
        "```markdown\n"
        "<!-- open comment\n"
        "$$\n"
        "```\n"
    )

    assert markdown_lint_issues_from_text(content) == []


def test_unclosed_math_or_comment_is_left_for_user_to_close(tmp_path):
    math_path = tmp_path / "math.md"
    math_source = "$$\n" + ("x = y\n" * 49)
    math_path.write_text(math_source)
    math_report = autofix_markdown_file(math_path)
    assert math_report["fixes"] == []
    assert math_report["warnings"][0]["kind"] == "math"
    assert math_path.read_text() == math_source

    comment_path = tmp_path / "comment.md"
    comment_source = "<!-- open\n" + ("comment text\n" * 210)
    comment_path.write_text(comment_source)
    comment_report = autofix_markdown_file(comment_path)
    assert comment_report["fixes"] == []
    assert comment_report["warnings"][0]["kind"] == "comment"
    assert comment_path.read_text() == comment_source


@pytest.mark.parametrize("status,expected", [(0, True), (1, False)])
def test_comment_filter_confirmation_is_unit_testable(
    monkeypatch, status, expected
):
    from pydifftools import continuous
    from pydifftools.continuous import confirm_restore_comment_filter

    monkeypatch.setattr(
        continuous.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], status, "", ""
        ),
    )

    assert confirm_restore_comment_filter("custom") is expected


def test_qt_fix_and_reload_windows_show_source_changes(tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QPushButton,
        QTextEdit,
    )

    from pydifftools.continuous import (
        show_markdown_fix_dialog,
        show_markdown_reload_dialog,
    )
    from pydifftools.wrap_sentences import autofix_markdown_file

    app = QApplication.instance() or QApplication([])
    seen = {}
    source_path = tmp_path / "deliberate_issue.md"
    source_path.write_text(
        "This deliberately lengthy source line contains a collection of "
        "words that should wrap before the end.\n"
    )
    report = autofix_markdown_file(source_path)
    fixed_source = source_path.read_text()
    assert len(report["fixes"]) == 1
    assert report["warnings"] == []
    assert markdown_lint_issues_from_text(fixed_source, 55) == []

    def inspect_fix_window():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Markdown source fixes"
        )
        seen["preview"] = dialog.findChild(QTextEdit).toPlainText()
        seen["button"] = dialog.findChild(QPushButton).text()
        seen["line_gutter"] = next(
            label
            for label in dialog.findChildren(QLabel)
            if "#666" in label.styleSheet()
        ).text()
        seen["heading"] = dialog.findChildren(QLabel)[0].text()
        dialog.findChild(QPushButton).click()

    QTimer.singleShot(0, inspect_fix_window)
    show_markdown_fix_dialog(report)
    assert "↳ of words" in seen["preview"]
    assert seen["button"] == "Done"
    assert "1" in seen["line_gutter"]
    assert "line 1" not in seen["heading"].lower()

    def inspect_reload_window():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Reload the Markdown source"
        )
        seen["reload_button"] = dialog.findChild(QPushButton).text()
        dialog.findChild(QPushButton).click()

    QTimer.singleShot(0, inspect_reload_window)
    show_markdown_reload_dialog()
    assert seen["reload_button"] == "I've reloaded"


def test_qt_unclosed_math_window_bolds_source_and_requests_confirmation():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QPushButton,
        QTextEdit,
    )

    from pydifftools.continuous import show_markdown_fix_dialog
    from pydifftools.wrap_sentences import unclosed_markdown_spans

    app = QApplication.instance() or QApplication([])
    math_source = "$$\n" + ("x = y\n" * 49)
    seen = {}

    def inspect_warning_window():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Markdown source fixes"
        )
        seen["details"] = dialog.findChildren(QLabel)[1].text()
        seen["html"] = dialog.findChild(QTextEdit).toHtml()
        button = dialog.findChild(QPushButton)
        seen["button"] = button.text()
        button.click()

    QTimer.singleShot(0, inspect_warning_window)
    confirmed = show_markdown_fix_dialog(
        {"fixes": [], "warnings": unclosed_markdown_spans(math_source)}
    )

    assert confirmed is True
    assert "Add $$" in seen["details"]
    assert "font-weight" in seen["html"] or "<b>" in seen["html"]
    assert seen["button"] == "I've fixed it"


def test_qt_unclosed_comment_window_shows_missing_close_marker():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QPushButton,
        QTextEdit,
    )

    from pydifftools.continuous import show_markdown_fix_dialog
    from pydifftools.wrap_sentences import unclosed_markdown_spans

    app = QApplication.instance() or QApplication([])
    comment_source = "<!-- this comment was not closed"
    seen = {}

    def inspect_warning_window():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Markdown source fixes"
        )
        seen["details"] = dialog.findChildren(QLabel)[1].text()
        seen["preview"] = dialog.findChild(QTextEdit).toPlainText()
        button = dialog.findChild(QPushButton)
        seen["button"] = button.text()
        button.click()

    QTimer.singleShot(0, inspect_warning_window)
    show_markdown_fix_dialog(
        {"fixes": [], "warnings": unclosed_markdown_spans(comment_source)}
    )

    assert "Add -->" in seen["details"]
    assert "this comment was not closed" in seen["preview"]
    assert seen["button"] == "I've fixed it"


@pytest.mark.parametrize("table", TABLES)
def test_protected_tables_are_never_flagged(tmp_path, table):
    path = tmp_path / "doc.md"
    path.write_text(table)
    wrchk(str(path), wrapnumber=5)


def test_protected_code_and_math_are_never_flagged(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "```python\n"
        "x = 'a very long line that would overflow any small width'\n"
        "```\n"
        "$$\n"
        "a + b + c + d + e + f + g + h + i + j + k + l + m + n\n"
        "$$\n"
    )
    wrchk(str(path), wrapnumber=5)


def test_wrchk_raises_systemexit_on_violations(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit) as excinfo:
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    assert excinfo.value.code == 1


def test_wrchk_clean_after_wr(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    wr(str(path), wrapnumber=30)
    wrchk(str(path), wrapnumber=30)


def test_wrchk_reports_line_and_file_name(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit):
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    out = capsys.readouterr().out
    assert f"{path}:1:" in out


def test_wrchk_latex_document(tmp_path):
    path = tmp_path / "doc.tex"
    path.write_text(
        "\\section{Title}\n"
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit):
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    wr(str(path), wrapnumber=30)
    wrchk(str(path), wrapnumber=30)
