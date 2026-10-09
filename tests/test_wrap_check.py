import os
import re
import subprocess
import sys

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
        "moved the extra words" in item["reason"]
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
    assert "run-on lines" in reason


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


def test_width_and_dependent_phrase_have_distinct_lint_rules():
    source = (
        "(see @fig:CaldararuTau) indicates that\n"
        "This is especially true, given that a comparison\n"
    )

    assert markdown_lint_issues_from_text(source, 55) == []
    assert markdown_lint_issues_from_text(source, 79) == []
    assert [
        message.split(":")[0]
        for _, message in markdown_lint_issues_from_text(source, 40)
    ] == ["trailing dependent phrase", "line too long"]


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
    # "time," is 26 characters before the actual maximum width, although
    # it is only 18 before the widest word boundary. Use the actual width.
    assert fixed.splitlines()[0].endswith("the classic")
    assert len(report["fixes"]) == 1
    path.write_text(line)
    autofix_markdown_file(path, wrapnumber=79, punctuation_slop=26)
    assert path.read_text().splitlines()[0].endswith(
        "rotational correlation time,"
    )


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
        seen["heading"] = dialog.findChildren(QLabel)[0].text()
        dialog.findChild(QPushButton).click()

    QTimer.singleShot(0, inspect_fix_window)
    show_markdown_fix_dialog(report)
    assert "↳ collection of words" in seen["preview"]
    assert seen["button"] == "Done"
    assert re.search(r"^ +1 This deliberately", seen["preview"], re.M)
    assert seen["preview"].count("\n") == 0
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


def test_qt_fix_window_groups_fixes_of_one_kind_onto_full_pages(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from PySide6.QtWidgets import QLabel, QTextEdit

    from pydifftools.continuous import show_markdown_fix_dialog

    app = QApplication.instance() or QApplication([])
    # from RM_ESR: many stray trailing spaces plus one other kind of fix
    source_path = tmp_path / "content.md"
    source_path.write_text(
        "".join(f"Sentence number {j} ends here. \n" for j in range(60))
        + "\n$$\nx = y\n$$ {#eq:tauFromLinewidth}\n"
    )
    report = autofix_markdown_file(source_path)
    assert len(report["fixes"]) == 61
    pages = []

    def inspect_page():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Markdown source fixes"
        )
        preview = dialog.findChild(QTextEdit).toPlainText()
        pages.append(
            {
                "heading": dialog.findChildren(QLabel)[0].text(),
                "details": dialog.findChildren(QLabel)[1].text(),
                "entries": preview.split("\n\n"),
            }
        )
        button = dialog.findChild(QPushButton)
        if button.text() == "Next":
            QTimer.singleShot(0, inspect_page)
        button.click()

    QTimer.singleShot(0, inspect_page)
    show_markdown_fix_dialog(report)

    trailing = [page for page in pages if "stray space" in page["details"]]
    crossref = [page for page in pages if "crossref" in page["details"]]
    # one kind per page, many fixes per page, and every fix shown once
    assert len(trailing) + len(crossref) == len(pages)
    assert len(crossref) == 1
    assert 1 < len(trailing) < 60
    assert all(len(page["entries"]) > 5 for page in trailing[:-1])
    assert sum(len(page["entries"]) for page in trailing) == 60
    assert f"(page 1 of {len(pages)})" in pages[0]["heading"]
    # a trailing-space entry is just the numbered line with its stray space
    # made visible, while other fixes also show the line after the fix
    assert re.fullmatch(
        r" +1 − Sentence number 0 ends here\.·", trailing[0]["entries"][0]
    )
    assert re.fullmatch(
        r" +64 − \$\$ \{#eq:tauFromLinewidth\}\n +64 \+ "
        r"\$\$\{#eq:tauFromLinewidth\}",
        crossref[0]["entries"][0],
    )


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


# {{{ keep line breaks close to git HEAD
# from RM_ESR, wrapped the way the manuscript already is
HEAD_PARAGRAPH = (
    "Existing Python libraries enable rapid development of a script\n"
    "that estimates the correlation time of these spectra.\n"
    "This script determines the field positions and amplitudes of the\n"
    "spectral lines for an entire variable-temperature experiment.\n"
    "It implements spline-based smoothing of the spectra in order to\n"
    "minimize the impact of any noise as part of this determination.\n"
)


def committed_source(tmp_path, text):
    """A content.md committed to a fresh git repository."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "content.md"
    path.write_text(text)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "content.md"], check=True
    )
    subprocess.run(
        [
            "git", "-C", str(tmp_path), "-c", "user.name=t",
            "-c", "user.email=t@example.org", "commit", "-q", "-m", "head",
        ],
        check=True,
    )
    return path


def numstat(path):
    """(added, removed) lines against git HEAD."""
    output = subprocess.run(
        ["git", "-C", str(path.parent), "diff", "--numstat", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return (int(output[0]), int(output[1])) if output else (0, 0)


def test_appended_words_restore_head_lines_and_stay_within_width(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    path.write_text(
        HEAD_PARAGRAPH.replace(
            "of these spectra.\n", "of these spectra across all samples.\n"
        ).replace(
            "rapid development of a script\n",
            "rapid development of a script in a few lines\n",
        )
    )
    # the first edit fits; the second pushes a line past 79 characters
    path.write_text(
        path.read_text().replace(
            "of the\nspectral",
            "of the three hyperfine lines, and of the\nspectral",
        )
    )

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    fixed = path.read_text()
    assert report["fixes"] and report["layout"] == []
    assert markdown_lint_issues_from_text(fixed, 79) == []
    # the HEAD line stays intact and the added words get one new line
    assert (
        "This script determines the field positions and amplitudes of the\n"
        "three hyperfine lines, and of the\n"
    ) in fixed
    assert "development of a script\nin a few lines\n" in fixed
    assert numstat(path) == (3, 1)


def test_stray_line_break_in_an_unchanged_line_is_rejoined(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    path.write_text(
        HEAD_PARAGRAPH.replace(
            "development of a script", "development\nof a script"
        )
    )

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH
    assert numstat(path) == (0, 0)
    assert "put those breaks back" in report["fixes"][0]["reason"]


def test_one_moved_line_break_is_moved_back(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    path.write_text(
        HEAD_PARAGRAPH.replace(
            "amplitudes of the\nspectral lines",
            "amplitudes of\nthe spectral lines",
        )
    )

    autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH


def test_joined_head_lines_past_the_width_get_heads_break_back(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    path.write_text(
        HEAD_PARAGRAPH.replace("in order to\nminimize", "in order to minimize")
    )

    autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH


def test_joined_head_lines_below_width_restore_the_deleted_break(tmp_path):
    head = "Water inside\nsmall pools stays liquid.\n"
    path = committed_source(tmp_path, head)
    path.write_text(head.replace("inside\nsmall", "inside small"))

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == head
    assert numstat(path) == (0, 0)
    assert report["layout"] == []
    assert "put those breaks back" in report["fixes"][0]["reason"]


def test_two_deleted_head_breaks_are_restored_automatically(tmp_path):
    head = "Water inside\nsmall pools\nstays liquid.\n"
    joined = head.replace("\n", " ").rstrip() + "\n"
    path = committed_source(tmp_path, head)
    path.write_text(joined)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == head
    assert report["layout"] == []
    (fix,) = report["fixes"]
    assert fix["before"] == joined.rstrip()
    assert fix["after"] == head.rstrip()


@pytest.mark.parametrize("dimensions_already_separate", [False, True])
def test_rm_esr_restores_full_head_lines_in_rewritten_sentence(
    tmp_path, dimensions_already_separate
):
    head = (
        "To improve mechanical stability and minimize\n"
        "vibrations, subsequent time-dependent\n"
        "ESR measurements\n"
        "(including the feedback-guided measurements)\n"
        "employed a different setup\n"
        "(as shown in @fig:Sample_holder_scheme_quartz).\n"
        "The end of the sample capillary tube\n"
        "(1.50 mm i.d., 1.80 mm o.d.),\n"
        "was inserted into a teflon tube support (3 mm o.d.)\n"
        "that was, in turn,\n"
    )
    edited = (
        "However, to improve mechanical stability and minimize\n"
        "vibrations, the ESR measurements presented in the main text\n"
        "employ a setup\n"
        "(as shown in @fig:Sample_holder_scheme_quartz)\n"
        "where the end of the sample capillary tube "
        "(1.50 mm i.d., 1.80 mm o.d.),\n"
        "is inserted into a teflon tube support (3 mm o.d.)\n"
        "that is, in turn,\n"
    )
    if dimensions_already_separate:
        edited = edited.replace("tube (1.50", "tube\n(1.50")
    path = committed_source(tmp_path, head)
    path.write_text(edited)
    assert numstat(path) == (7, 9 if dimensions_already_separate else 10)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    expected = edited.replace(
        "the ESR measurements presented",
        "the\nESR measurements\npresented",
    ).replace("tube (1.50", "tube\n(1.50")
    assert path.read_text() == expected
    assert report["fixes"] and report["layout"] == []
    from pydifftools.match_spaces import run

    reference = tmp_path / "reference.md"
    reference.write_text(head)
    matched = tmp_path / "matched.md"
    matched.write_text(edited)
    run([str(reference), str(matched)])
    assert matched.read_text() == expected
    # Automatic alignment preserves both unchanged HEAD lines.
    assert numstat(path) == (8, 8)


def test_embedded_head_line_restores_both_boundaries_together(tmp_path):
    path = committed_source(tmp_path, "Before\nESR measurements\nAfter.\n")
    edited = "Changed before ESR measurements changed after.\n"
    path.write_text(edited)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    expected = (
        "Changed before\nESR measurements\nchanged after."
    )
    assert path.read_text() == expected + "\n"
    assert report["layout"] == []
    (fix,) = report["fixes"]
    assert fix["before"] == edited.rstrip()
    assert fix["after"] == expected


@pytest.mark.parametrize("count", [1, 5, 30])
def test_cpb_and_wmatch_restore_scattered_reference_lines(tmp_path, count):
    from pydifftools.match_spaces import run

    head = "\n\n".join(
        f"Former intro {number}\nStable component {number}\n"
        f"former outro {number}."
        for number in range(count)
    ) + "\n"
    current = "\n\n".join(
        f"Changed intro {number} Stable component {number} "
        f"changed outro {number}."
        for number in range(count)
    ) + "\n"
    expected = "\n\n".join(
        f"Changed intro {number}\nStable component {number}\n"
        f"changed outro {number}."
        for number in range(count)
    ) + "\n"
    path = committed_source(tmp_path, head)
    path.write_text(current)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == expected
    assert len(report["fixes"]) == count
    assert report["layout"] == []
    reference = tmp_path / "reference.md"
    reference.write_text(head)
    run([str(reference), str(path)])
    assert path.read_text() == expected
    assert not any(
        autofix_markdown_file(path, wrapnumber=79, git_head=True).values()
    )
    run([str(reference), str(path)])
    assert path.read_text() == expected


def test_two_moved_line_breaks_in_one_hunk_are_fixed(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    edited = HEAD_PARAGRAPH.replace(
        "amplitudes of the\nspectral lines",
        "amplitudes\nof the spectral lines",
    ).replace(
        "variable-temperature experiment.\nIt implements",
        "variable-temperature experiment.\nIt\nimplements",
    )
    path.write_text(edited)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH
    assert report["layout"] == []
    (fix,) = report["fixes"]
    assert fix["line"] == 3
    assert fix["after"] + "\n" in HEAD_PARAGRAPH


def test_removed_words_keep_their_line_break(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    edited = HEAD_PARAGRAPH.replace(
        "development of a script\nthat", "development\nthat"
    )
    path.write_text(edited)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == edited
    assert report["fixes"] == [] and report["layout"] == []


def test_new_paragraph_keeps_the_writers_line_breaks(tmp_path):
    path = committed_source(tmp_path, HEAD_PARAGRAPH)
    new_paragraph = (
        "\nThese estimates\n"
        "depend only weakly on the choice of smoothing.\n"
    )
    path.write_text(HEAD_PARAGRAPH + new_paragraph)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH + new_paragraph
    assert report["fixes"] == [] and report["layout"] == []


def test_whole_file_is_still_linted_against_head(tmp_path):
    # a problem that git HEAD already has still has to be fixed
    path = committed_source(
        tmp_path, HEAD_PARAGRAPH.replace("spectra.\n", "spectra. \n")
    )

    autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert path.read_text() == HEAD_PARAGRAPH


def test_file_outside_git_is_linted_without_head(tmp_path):
    path = tmp_path / "content.md"
    path.write_text(
        HEAD_PARAGRAPH.replace(
            "development of a script", "development\nof a script"
        )
    )

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    assert report["fixes"] == [] and report["layout"] == []


# }}}


def test_rewritten_sentence_reuses_whitespace_between_matched_words(tmp_path):
    # Partial matching lines reuse reference whitespace too, before the
    # separate complete-line preservation pass.
    head = (
        "Peric *et al.* also observed that\n"
        "even similarly sized nitroxide probes can report\n"
        "different rotational dynamics in bulk water.\n"
    )
    rewrite = (
        "Peric *et al.* also observed that\n"
        "the rotational dynamics\n"
        "of different small nitroxide probes\n"
        "in bulk water\n"
        "differ significantly.\n"
    )
    path = committed_source(tmp_path, head)
    path.write_text(rewrite)

    report = autofix_markdown_file(path, wrapnumber=79, git_head=True)

    expected = rewrite.replace("dynamics\nof", "dynamics of")
    assert path.read_text() == expected
    assert expected.split() == rewrite.split()
    assert len(report["fixes"]) == 1 and report["layout"] == []
    assert not any(
        autofix_markdown_file(path, wrapnumber=79, git_head=True).values()
    )


@pytest.mark.parametrize("ref", [None, "@", "jf_last", "baseline", "hash"])
def test_diff_lint_selects_index_or_revision_for_nested_file(tmp_path, ref):
    head = "Water inside\nsmall pools\nstays liquid.\n"
    latest = "Water inside small\npools stays\nliquid.\n"
    staged = "Water\ninside small pools\nstays liquid.\n"
    committed_source(tmp_path, head)
    directory = tmp_path / "nested folder"
    directory.mkdir()
    path = directory / "source notes.md"
    path.write_text(head)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "."], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=t",
         "-c", "user.email=t@example.org", "commit", "-qm", "nested"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "tag", "jf_last"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "branch", "baseline"], check=True
    )
    if ref == "hash":
        ref = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    path.write_text(latest)
    subprocess.run(
        ["git", "-C", str(directory), "add", path.name], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=t",
         "-c", "user.email=t@example.org", "commit", "-qm", "new HEAD"],
        check=True,
    )
    path.write_text(staged)
    subprocess.run(
        ["git", "-C", str(directory), "add", path.name], check=True
    )
    path.write_text("Water inside small pools stays liquid.\n")

    report = autofix_markdown_file(
        path, wrapnumber=79, git_index=True, git_ref=ref,
        # Explicit refs must also override legacy HEAD selection.
        git_head=True,
    )

    expected = staged if ref is None else (latest if ref == "@" else head)
    label = "Git index" if ref is None else f"git {ref}"
    assert path.read_text() == expected
    assert label in report["fixes"][0]["reason"]
    assert report["layout"] == []
    assert subprocess.run(
        ["git", "-C", str(directory), "show", ":./" + path.name],
        capture_output=True, text=True, check=True,
    ).stdout == staged
    assert subprocess.run(
        ["git", "-C", str(directory), "show", "HEAD:./" + path.name],
        capture_output=True, text=True, check=True,
    ).stdout == latest


@pytest.mark.parametrize("ref", [None, "@", "jf_last"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_diff_lint_restores_html_comment_layout(tmp_path, ref, ending):
    reference = (
        "Before unchanged.\n"
        "<!-- this section seems to have been moved from after paragraph\n"
        "that ends $w_1 \\propto d_i$ -->\n"
        "These are much longer/slower than the previous result.\n"
        "<!--\n"
        "At 263 K (1000/T = 1000/3.80228),\n"
        "(1) small RM aggregates ($w_0=3$),\n"
        "observed $\\tau_c\\approx 6.2820\\;\\mathrm{ns}="
        "10^{-8.201}\\;\\text{s}$,\n"
        "(2) large RM aggregates ($w_0=20$),\n"
        "observed $\\tau_c\\approx 164.51\\;\\mathrm{ps}="
        "10^{-9.7838}\\;\\text{s}$.\n"
        "-->\n"
        "Thus, the observed signal comes almost entirely\n"
        "from the internal rotation of the spin probe.\n"
    )
    path = committed_source(tmp_path, reference)
    subprocess.run(
        ["git", "-C", str(tmp_path), "tag", "jf_last"], check=True
    )
    current = reference.replace(
        "moved from after paragraph\nthat ends",
        "moved\nfrom after paragraph that ends",
    ).replace(
        "(1) small RM aggregates ($w_0=3$),\nobserved",
        "(1) small RM aggregates ($w_0=3$), observed",
    ).replace(
        "\\approx 6.2820", "\\approx\n6.2820"
    ).replace("-->\nThus", "--> Thus")
    path.write_bytes(current.replace("\n", ending).encode())

    report = autofix_markdown_file(
        path, wrapnumber=79, git_index=True, git_ref=ref,
    )

    assert path.read_bytes() == reference.replace("\n", ending).encode()
    assert report["fixes"] and report["warnings"] == []
    assert not any(
        autofix_markdown_file(
            path, wrapnumber=79, git_index=True, git_ref=ref,
        ).values()
    )


@pytest.mark.parametrize("ref", [None, "@"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_diff_lint_applies_leading_whitespace_fixes(tmp_path, ref, ending):
    reference = "  Visible words.\n<!--\n\tHidden words.\n-->\n"
    path = committed_source(tmp_path, reference)
    current = reference.replace("  Visible", " Visible").replace("\t", "   ")
    path.write_bytes(current.replace("\n", ending).encode())

    report = autofix_markdown_file(
        path, wrapnumber=79, git_index=True, git_ref=ref,
    )

    assert path.read_bytes() == reference.replace("\n", ending).encode()
    assert report["fixes"] and report["warnings"] == []
    assert not any(
        autofix_markdown_file(
            path, wrapnumber=79, git_index=True, git_ref=ref,
        ).values()
    )


@pytest.mark.parametrize("ref", [None, "@", "jf_last"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_diff_lint_restores_equations_and_keeps_numeric_edit(
    tmp_path, ref, ending,
):
    reference = (
        "The SDE equation:\n"
        r"$$\tau_c= \frac{4\pi\eta r^3}{3 k_B T}$${#eq:SDE}" + "\n"
        "The Einstein relation:\n"
        r"$$\eta = \frac{k_B T}{6\pi D r_{solv}},$$" + "\n"
        "Taking logarithms yields:\n"
        r"$$\log_{10}(\tau_c) =" + "\n"
        r"c+\frac{E_a}{2.3026 RT},$${#eq:arrhenius}" + "\n"
        "The viscosity is:\n"
        "$0.51\\ \\mathrm{mPa}\\cdot\\mathrm{s}$\n"
    )
    path = committed_source(tmp_path, reference)
    subprocess.run(
        ["git", "-C", str(tmp_path), "tag", "jf_last"], check=True,
    )
    current = reference.replace("$$", "$$\n", 1).replace(
        r"T}$${#eq:SDE}", "T}\n$${#eq:SDE}",
    ).replace(
        r"$$\eta", "$$\n" + r"\eta",
    ).replace(
        "},$$", "},\n$$",
    ).replace(
        r"$$\log", "$$\n" + r"\log",
    ).replace(
        "RT},$$", "RT},\n$$",
    ).replace("$0.51\\ ", "$0.506\\\n")
    path.write_bytes(current.replace("\n", ending).encode())

    report = autofix_markdown_file(
        path, wrapnumber=79, git_index=True, git_ref=ref,
    )

    assert path.read_bytes() == reference.replace(
        "0.51", "0.506",
    ).replace("\n", ending).encode()
    assert report["fixes"] and report["warnings"] == []
    assert not any(
        autofix_markdown_file(
            path, wrapnumber=79, git_index=True, git_ref=ref,
        ).values()
    )


def test_comment_text_is_exempt_from_prose_fixes():
    comment = (
        "<!-- A hidden sentence. Another hidden sentence with a long "
        "description, and a dependent phrase. \n<JFcomm> -->\n"
    )
    assert markdown_lint_issues_from_text(comment, wrapnumber=25) == []


def test_new_html_comment_keeps_its_source_layout(tmp_path):
    reference = "Visible prose.\n"
    path = committed_source(tmp_path, reference)
    current = reference + (
        "<!-- New hidden sentence. Another sentence with many extra words. \n"
        "<JFcomm> is just a literal example inside this comment. -->\n"
    )
    path.write_text(current)
    report = autofix_markdown_file(path, wrapnumber=25, git_index=True)
    assert path.read_text() == current
    assert not any(report.values())


def test_diff_lint_reads_updated_index_on_next_build(tmp_path):
    first = "Water inside\nsmall pools stays liquid.\n"
    second = "Water inside small pools\nstays liquid.\n"
    path = committed_source(tmp_path, first)
    for baseline in (first, second):
        path.write_text(baseline)
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", path.name], check=True
        )
        path.write_text("Water inside small pools stays liquid.\n")
        autofix_markdown_file(path, wrapnumber=79, git_index=True)
        assert path.read_text() == baseline


@pytest.mark.parametrize("baseline", ["index", "missing-ref", "@", ""])
@pytest.mark.parametrize("in_repo", [False, True])
def test_diff_lint_unavailable_baseline_policy(tmp_path, baseline, in_repo):
    if in_repo:
        committed_source(tmp_path, "Committed source.\n")
    path = tmp_path / "untracked.md"
    original = "Water stays liquid. \n"
    path.write_text(original)
    if baseline == "index":
        report = autofix_markdown_file(path, git_index=True)
        assert path.read_text() == "Water stays liquid.\n"
        assert report["fixes"] and not report["layout"]
    else:
        with pytest.raises(RuntimeError, match="diff-lint baseline") as error:
            autofix_markdown_file(path, git_index=True, git_ref=baseline)
        assert repr(baseline) in str(error.value)
        assert str(path) in str(error.value)
        assert path.read_text() == original


@pytest.mark.parametrize("explicit", [False, True])
def test_diff_lint_without_git(monkeypatch, tmp_path, explicit):
    from pydifftools import wrap_sentences

    path = tmp_path / "source.md"
    path.write_text("Water stays liquid. \n")

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git is unavailable")

    monkeypatch.setattr(wrap_sentences.subprocess, "Popen", missing_git)
    if explicit:
        with pytest.raises(RuntimeError, match="git is unavailable"):
            autofix_markdown_file(path, git_ref="@")
        assert path.read_text() == "Water stays liquid. \n"
    else:
        autofix_markdown_file(path, git_index=True)
        assert path.read_text() == "Water stays liquid.\n"


def test_qt_diff_fixes_fill_pages_with_double_line_breaks(tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from PySide6.QtWidgets import QLabel, QTextEdit

    from pydifftools.continuous import show_markdown_fix_dialog

    app = QApplication.instance() or QApplication([])
    count = 60
    head = "\n\n".join(
        f"Former intro {j}\nStable component {j}\nformer outro {j}."
        for j in range(count)
    ) + "\n"
    current = "\n\n".join(
        f"Changed intro {j} Stable component {j} changed outro {j}."
        for j in range(count)
    ) + "\n"
    path = committed_source(tmp_path, head)
    path.write_text(current)
    report = autofix_markdown_file(path, wrapnumber=79, git_index=True)
    expected = "\n\n".join(
        f"Changed intro {j}\nStable component {j}\nchanged outro {j}."
        for j in range(count)
    ) + "\n"
    # Every hunk must already be applied before the notice opens.
    assert path.read_text() == expected
    assert len(report["fixes"]) == count
    pages = []

    def inspect():
        dialog = next(
            widget for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog) and widget.isVisible()
        )
        preview = dialog.findChild(QTextEdit)
        pages.append({
            "text": preview.toPlainText(),
            "heading": dialog.findChildren(QLabel)[0].text(),
            "details": dialog.findChildren(QLabel)[1].text(),
            "scroll": preview.verticalScrollBar().maximum(),
            "spare": (
                preview.viewport().height()
                - preview.document().size().height()
            ),
            "row_height": (
                preview.document().firstBlock().layout().lineAt(0).height()
            ),
        })
        button = dialog.findChild(QPushButton)
        if button.text() == "Next":
            QTimer.singleShot(0, inspect)
        button.click()

    QTimer.singleShot(0, inspect)
    show_markdown_fix_dialog(report)

    assert 1 < len(pages) < count
    assert all(len(page["text"].split("\n\n")) > 1 for page in pages[:-1])
    assert all(page["scroll"] == 0 for page in pages)
    # Each next hunk would add one original line plus its blank separator.
    assert all(page["spare"] < 2 * page["row_height"] for page in pages[:-1])
    assert all("automatically" in page["heading"] for page in pages)
    assert all("Git index" in page["details"] for page in pages)
    assert [
        int(number) for page in pages
        for number in re.findall(r"Stable component (\d+)", page["text"])
    ] == list(range(count))
    assert not any(
        autofix_markdown_file(path, wrapnumber=79, git_index=True).values()
    )


@pytest.mark.parametrize("deleted_breaks", [False, True])
@pytest.mark.parametrize("baseline", ["HEAD", "index", "jf_last"])
def test_qt_diff_fix_notice_marks_applied_changes_on_original_source(
    tmp_path, deleted_breaks, baseline
):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QLabel
    from PySide6.QtWidgets import QPushButton, QTextEdit

    from pydifftools.continuous import show_markdown_fix_dialog

    app = QApplication.instance() or QApplication([])
    head_text = (
        "Water inside\nsmall pools\nstays liquid.\n"
        if deleted_breaks else HEAD_PARAGRAPH
    )
    path = committed_source(tmp_path, head_text)
    subprocess.run(
        ["git", "-C", str(tmp_path), "tag", "jf_last"], check=True
    )
    edited = (
        head_text.replace("\n", " ").rstrip() + "\n"
        if deleted_breaks else
        HEAD_PARAGRAPH.replace(
            "amplitudes of the\nspectral lines",
            "amplitudes\nof the spectral lines",
        ).replace(
            "experiment.\nIt implements", "experiment.\nIt\nimplements"
        )
    )
    path.write_text(edited)
    report = autofix_markdown_file(
        path, wrapnumber=79, git_head=True,
        git_index=baseline == "index",
        git_ref="jf_last" if baseline == "jf_last" else None,
    )
    seen = {}

    def inspect():
        dialog = next(
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog) and widget.isVisible()
        )
        seen["heading"] = dialog.findChildren(QLabel)[0].text()
        seen["details"] = dialog.findChildren(QLabel)[1].text()
        seen["preview"] = dialog.findChild(QTextEdit).toPlainText()
        dialog.findChild(QPushButton).click()

    QTimer.singleShot(0, inspect)
    show_markdown_fix_dialog(report)

    label = "Git index" if baseline == "index" else f"git {baseline}"
    assert "fixed this source hunk automatically" in seen["heading"]
    assert label in seen["details"]
    assert "minimize the diff" in seen["details"]
    assert "left them" not in seen["details"]
    assert path.read_text() == head_text
    original = "\n".join(
        row[7:] for row in seen["preview"].splitlines()
    ).replace("↳×", "").replace("↳", "")
    assert original == report["fixes"][0]["before"]
    assert seen["preview"].count("↳") == (2 if deleted_breaks else 3)
    if deleted_breaks:
        assert "Water inside↳ small pools↳ stays liquid." in seen["preview"]
        assert "↳×" not in seen["preview"]
    else:
        assert seen["preview"].count("↳×") == 2


@pytest.mark.parametrize(
    "before, after, marked, colors",
    [
        (
            "capillary tube (1.50 mm i.d., 1.80 mm o.d.),",
            "capillary tube\n(1.50 mm i.d., 1.80 mm o.d.),",
            "capillary tube↳ (1.50 mm i.d., 1.80 mm o.d.),",
            ["#188038"],
        ),
        (
            "capillary tube\n(1.50 mm i.d., 1.80 mm o.d.),",
            "capillary tube (1.50 mm i.d., 1.80 mm o.d.),",
            "capillary tube↳×\n(1.50 mm i.d., 1.80 mm o.d.),",
            ["#c62828"],
        ),
        (
            "a b\nc d",
            "a\nb c d",
            "a↳ b↳×\nc d",
            ["#188038", "#c62828"],
        ),
        (
            "same same same\nsame",
            "same\nsame same same",
            "same↳ same same↳×\nsame",
            ["#188038", "#c62828"],
        ),
        (
            "a b\nc d",
            "a\nb\nc d",
            "a↳ b\nc d",
            ["#188038"],
        ),
        (
            "Text <JFcom> & details\ncontinued here.",
            "Text\n<JFcom> & details continued here.",
            "Text↳ <JFcom> & details↳×\ncontinued here.",
            ["#188038", "#c62828"],
        ),
        (
            "alpha\n    beta gamma",
            "alpha beta\ngamma",
            "alpha↳×\n    beta↳ gamma",
            ["#c62828", "#188038"],
        ),
    ],
)
def test_qt_break_markers_keep_original_source_and_colors(
    before, after, marked, colors
):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from PySide6.QtWidgets import QLabel, QTextEdit

    from pydifftools.continuous import show_markdown_fix_dialog

    app = QApplication.instance() or QApplication([])
    seen = {}

    def inspect():
        dialog = next(
            widget for widget in app.topLevelWidgets()
            if isinstance(widget, QDialog) and widget.isVisible()
        )
        preview = dialog.findChild(QTextEdit)
        seen["text"] = preview.toPlainText()
        seen["wrap"] = preview.lineWrapMode()
        seen["details"] = dialog.findChildren(QLabel)[1].text()
        document = preview.document()
        cursor = document.find("↳")
        seen["colors"] = []
        while not cursor.isNull():
            seen["colors"].append(
                cursor.charFormat().foreground().color().name()
            )
            cursor = document.find("↳", cursor)
        cursor = document.find("×")
        if not cursor.isNull():
            seen["cross_color"] = (
                cursor.charFormat().foreground().color().name()
            )
        dialog.findChild(QPushButton).click()

    QTimer.singleShot(0, inspect)
    show_markdown_fix_dialog(
        {
            "fixes": [
                {"line": 648, "reason": "Restore breaks.",
                 "before": before, "after": after}
            ],
            "warnings": [],
        }
    )

    assert seen["text"] == "\n".join(
        f"{648 + offset:>6} {row}"
        for offset, row in enumerate(marked.split("\n"))
    )
    assert seen["colors"] == colors
    assert seen["wrap"] == QTextEdit.LineWrapMode.NoWrap
    assert "Original source:" in seen["details"]
    if "×" in marked:
        assert seen["cross_color"] == "#c62828"


def test_qt_fix_windows_create_their_own_application():
    # cpb shows these windows without a QApplication; constructing the
    # dialog first aborted the whole process
    pytest.importorskip("PySide6")
    script = (
        "from PySide6.QtWidgets import QDialog\n"
        "QDialog.exec = lambda self: 0\n"
        "from pydifftools.continuous import (\n"
        "    show_markdown_fix_dialog, show_markdown_reload_dialog)\n"
        "show_markdown_fix_dialog({'fixes': [{'line': 1, 'reason': 'r',\n"
        "    'before': 'a ', 'after': 'a'}], 'warnings': []})\n"
        "show_markdown_reload_dialog()\n"
        "print('shown')\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "shown"


def test_fix_reasons_cover_one_or_more_lines(tmp_path):
    # one reason heads a whole page of fixes, so it never says "a line"
    path = tmp_path / "source.md"
    path.write_text(
        "First sentence ends here. A second sentence begins.\n"
        "This line is a run-on line that goes on well past the width.\n"
        "It ends with a stray space. \n"
    )

    report = autofix_markdown_file(path, wrapnumber=55)

    reasons = {fix["reason"] for fix in report["fixes"]}
    assert len(reasons) == 3
    assert all(reason.startswith("One or more ") for reason in reasons)
    assert any(
        "<b>always start sentences on new lines</b>" in reason
        for reason in reasons
    )


@pytest.mark.parametrize(
    "typed, fixed",
    [
        # from RM_ESR: typed as <JFcomm>, which the comment filter ignores
        ("JFcomm", "JFcom"),
        ("RScomment-left", "RScom-left"),
        ("jfComm-right", "jfcom-right"),
    ],
)
def test_misspelled_comment_tags_are_corrected(tmp_path, typed, fixed):
    path = tmp_path / "source.md"
    path.write_text(
        f"Some text\n<{typed}>\n  fill in question marks\n</{typed}>\n"
        "more.\n"
    )

    issues = markdown_lint_issues_from_text(path.read_text(), 79)
    report = autofix_markdown_file(path, wrapnumber=79)

    assert [message.split(":")[0] for _, message in issues] == [
        "misspelled comment tag"
    ] * 2
    assert path.read_text() == (
        f"Some text\n<{fixed}>\n  fill in question marks\n</{fixed}>\n"
        "more.\n"
    )
    assert report["fixes"][0]["reason"].startswith("One or more ")


def test_correct_comment_tags_and_code_are_left_alone():
    source = (
        "<JFcom>\nnote\n</JFcom>\n<comment>\nold\n</comment>\n"
        "\x60\x60\x60\n<JFcomm>\n\x60\x60\x60\n"
    )

    assert markdown_lint_issues_from_text(source, 79) == []
