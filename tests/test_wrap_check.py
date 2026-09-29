import re
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


def test_lint_line_numbers_survive_labeled_display_math():
    # normalizing "$${#eq:x}" for wrapping splits it onto two lines, which
    # must not shift the line numbers reported for later prose
    source = (
        "Intro.\n$$\nx = y\n$${#eq:x}\nwhere this sentence ends. "
        "Another starts.\n"
    )

    ((line, message),) = markdown_lint_issues_from_text(source, 55)

    assert line == 5
    assert message.startswith("sentence ends mid-line")


def test_long_line_fix_splits_at_the_word_after_the_break():
    # "for" also starts the line, but wr breaks before the second one
    source = (
        "for $30\\;\\text{s}$ ($3\\times$ for AOT) with some more words "
        "added.\n"
    )
    message = (
        "line too long: wr would break after '($3\\times$' (before 'for'); "
        "move 'for' onward to the next line, or shorten this sentence"
    )

    fixed, _, _, _ = apply_markdown_issue_fix(source, 1, message)

    assert fixed.startswith("for $30\\;\\text{s}$ ($3\\times$\nfor AOT)")


def test_single_trailing_space_is_flagged_and_removed(tmp_path):
    # from RM_ESR: a sentence ending in a stray space
    path = tmp_path / "source.md"
    path.write_text("It melts near 238&nbsp;K. \nIn contrast, it stays.\n")

    issues = markdown_lint_issues_from_text(path.read_text(), wrapnumber=55)
    autofix_markdown_file(path)

    assert (1, "trailing space") in [
        (line, message.split(":")[0]) for line, message in issues
    ]
    fixed = path.read_text()
    assert fixed.startswith("It melts near 238&nbsp;K.\nIn contrast,")
    assert " \n" not in fixed


def test_double_trailing_space_hard_break_is_allowed():
    source = "The first line ends here with a break  \nand continues.\n"

    assert markdown_lint_issues_from_text(source, wrapnumber=55) == []


@pytest.mark.parametrize(
    "detached",
    [
        # equation markers must sit directly on the closing $$
        "Intro.\n$$\nx = y\n$$ {#eq:x}\nwhere this holds.\n",
        "Intro.\n$$\nx = y\n$$\n{#eq:x}\nwhere this holds.\n",
        # figure markers must sit directly on the closing ) (from eigenmode)
        "![A caption.](./media/BothProbes_Bfields.png)\n"
        '{#fig:ProbeMagFieldsDrawing width="4in"}\n',
        # and must not be split across lines (from RM_ESR)
        "![A caption for\nspectroscopy.](Figures/simple_oned_CAT16.png)"
        "{#fig:justSpectraCat16\nwidth=4in}\n",
    ],
)
def test_detached_crossref_marker_is_flagged_and_joined(tmp_path, detached):
    path = tmp_path / "source.md"
    path.write_text(detached)

    issues = markdown_lint_issues_from_text(detached, wrapnumber=55)
    report = autofix_markdown_file(path)

    fixed = path.read_text()
    assert [message.split(":")[0] for _, message in issues] == [
        "detached crossref marker"
    ]
    assert report["fixes"]
    assert markdown_lint_issues_from_text(fixed, wrapnumber=55) == []
    assert re.search(r"(\$\$|\))\{#(eq|fig):[^}\n]*\}", fixed)


def test_figure_crossref_marker_is_never_split_from_its_figure(tmp_path):
    # from RM_ESR: a caption spanning lines, ending in a marker with
    # attributes; wr and the linter must treat "...){#fig:... }" as one word
    source = (
        "![Room temperature ESR of 100 mM TEMPO-SO~4~ RMs with water "
        "loading $w_0=30$ in isooctane dispersant (blue), single HE "
        "simulation (orange), multi HE simulation "
        "(green)](Figures/HE_Easyspin_Simul_100mM.png)\n"
        "{#fig:HESimul width=5.5in}\n"
    )
    path = tmp_path / "source.md"
    path.write_text(source)

    wr(str(path), 55)

    wrapped = path.read_text()
    assert (
        "(green)](Figures/HE_Easyspin_Simul_100mM.png)"
        "{#fig:HESimul width=5.5in}\n"
    ) in wrapped
    assert markdown_lint_issues_from_text(wrapped, wrapnumber=55) == []


def test_wr_keeps_equation_marker_on_closing_dollars(tmp_path):
    path = tmp_path / "source.md"
    path.write_text(
        "Intro.\n$$\nx = y\n$$ {#eq:tauFromLinewidth}\nwhere this holds.\n"
    )

    wr(str(path), 55)

    wrapped = path.read_text()
    assert "\n$${#eq:tauFromLinewidth}\n" in wrapped
    assert markdown_lint_issues_from_text(wrapped, wrapnumber=55) == []


def test_autofix_fixes_every_line_in_one_pass_from_the_end(tmp_path):
    path = tmp_path / "source.md"
    paragraph = "First sentence ends here. A second sentence begins.\n"
    path.write_text("\n".join([paragraph] * 30))

    report = autofix_markdown_file(path)

    fixed = path.read_text()
    assert len(report["fixes"]) == 30
    assert [fix["line"] for fix in report["fixes"]] == list(range(1, 60, 2))
    assert fixed.count("\n\n") == 29
    assert markdown_lint_issues_from_text(fixed, wrapnumber=55) == []


def test_only_lines_longer_than_the_width_are_too_long():
    # from RM_ESR: short lines ending on a clause used to be flagged, since
    # wr broke at a comma or paren even when the rest of the line fit
    source = (
        "(see @fig:CaldararuTau) indicates that\n"
        "This is especially true, given that a comparison\n"
    )

    assert markdown_lint_issues_from_text(source, 55) == []
    assert markdown_lint_issues_from_text(source, 79) == []
    assert [
        message.split(":")[0]
        for _, message in markdown_lint_issues_from_text(source, 40)
    ] == ["line too long"]


def test_long_line_breaks_early_on_a_nearby_clause(tmp_path):
    # from RM_ESR: several clauses on one line that grew past 79
    line = (
        "Finally, it estimates the rotational correlation time, "
        "*via* the classic Kivelson equation, as a function of temperature.\n"
    )
    path = tmp_path / "source.md"
    path.write_text(line)

    report = autofix_markdown_file(path, wrapnumber=79)

    fixed = path.read_text()
    assert fixed.split() == line.split()
    assert all(len(text) <= 79 for text in fixed.splitlines())
    # the widest break is after "classic" (72 characters); "time," is 18
    # characters before that, within the slop, so the line ends on it
    assert fixed.splitlines()[0].endswith("rotational correlation time,")
    assert len(report["fixes"]) == 1


def test_clause_far_before_the_width_does_not_force_an_early_break():
    line = (
        "Finally, it estimates the rotational correlation time of the "
        "probe and many other ordinary words here.\n"
    )

    first = wrap_prose(line, 79).splitlines()[0]

    assert first.startswith("Finally, it estimates")
    assert len(first) > 70


@pytest.mark.parametrize("width", [20, 45, 55, 79])
def test_wr_never_runs_past_the_width(width):
    text = (
        "This script determines the field positions, and amplitudes, of the "
        "spectral lines (for an entire variable-temperature experiment) -- "
        "and it implements spline-based smoothing of the spectra.\n"
    )

    wrapped = wrap_prose(text, width)

    assert all(len(line) <= width for line in wrapped.splitlines())
    assert markdown_lint_issues_from_text(wrapped, width) == []


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
    assert "↳ collection of words" in seen["preview"]
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
