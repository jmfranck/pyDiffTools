"""Regression cases for the shared word/whitespace alignment pipeline."""

import pytest
from pathlib import Path

from pydifftools.line_alignment import align_line_breaks, minimal_opcodes
from pydifftools import line_alignment
from pydifftools import wrap_sentences
from pydifftools.match_spaces import run
from pydifftools.wrap_sentences import (
    autofix_markdown_file,
    check_prose,
    wrap_prose,
)


def test_minimal_word_diff_with_ambiguous_matches(monkeypatch):
    # SequenceMatcher retains only "t" here; a minimal edit retains "de".
    # The user's surrounding/inter-hunk context setting must not merge edits.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.interHunkContext")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "20")
    before, after = list("tide"), list("diet")
    operations = minimal_opcodes(before, after)
    cost = sum(
        (b - a) + (d - c) for op, a, b, c, d in operations if op != "equal"
    )
    assert cost == 4
    for op, a, b, c, d in operations:
        if op == "equal":
            assert before[a:b] == after[c:d]


def test_partial_matching_lines_restore_whitespace_first(tmp_path):
    reference = "First\talpha beta\nSecond  gamma delta\n"
    current = "First changed alpha beta Second changed gamma delta\n"
    expected = "First\tchanged alpha beta\nSecond  changed gamma delta\n"
    (result,) = align_line_breaks(reference, current)
    assert result["aligned"] == expected
    assert result["aligned"].split() == current.split()
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    new.write_text(current)
    run([str(old), str(new)])
    assert new.read_text() == expected
    run([str(old), str(new)])
    assert new.read_text() == expected


@pytest.mark.parametrize("reference,current", [
    (
        r"the TEMPO-SO~4~ probe ($32.9;\text{kJ}/\text{mol}$"
        "(@fig:DodecaTSO4TempCycle, blue),\nwhich\n",
        r"the TEMPO-SO~4~ probe ($32.9;\text{kJ}/\text{mol}$"
        " (@fig:DodecaTSO4TempCycle, blue),\nwhich\n",
    ),
    (
        r"the TEMPO-SO~4~ probe inside small RMs dispersed in"
        "\ndodecane ($32.9;\\text{kJ}/\\text{mol}$ : "
        "@fig:DodecaTSO4TempCycle, blue),\nwhich\n",
        r"the TEMPO-SO~4~ probe inside small RMs dispersed in"
        "\ndodecane ($32.9;\\text{kJ}/\\text{mol}$: "
        "@fig:DodecaTSO4TempCycle, blue),\nwhich\n",
    ),
    ("First $x$ (reference).\n", "First $x$(reference).\n"),
    ("First $x$: reference.\n", "First $x$ : reference.\n"),
    ("First words continue here.\n", "First words  \ncontinue here.\n"),
    ("A long unchanged introductory line stays here.\n"
     "First words\\\ncontinue here.\n",
     "A long unchanged introductory line stays here.\n"
     "First words\\ continue here.\n"),
    ("Keep ordinary spaces.\n", "Keep\u00a0ordinary\u2004spaces.\n"),
    (r"Use $\text{a,b}$ here." + "\n",
     r"Use $\text{a, b}$ here." + "\n"),
    (r"Use $\text{a, b}$ here." + "\n",
     r"Use $\text{a,b}$ here." + "\n"),
    (r"Use $\text{a,{b,c}}$ here." + "\n",
     r"Use $\text{a, {b, c}}$ here." + "\n"),
    (r"Use $\text{a \text{b} c,d}$ here." + "\n",
     r"Use $\text{a \text{b} c, d}$ here." + "\n"),
    (r"Use $\alpha{}b$ here." + "\n",
     r"Use $\alpha b$ here." + "\n"),
    (r"Use $\custom{a,b}$ here." + "\n",
     r"Use $\custom{a, b}$ here." + "\n"),
    ("Use $<!-- hidden words -->$ here.\n",
     "Use $<!--hidden words-->$ here.\n"),
])
def test_rendered_spacing_survives_shared_alignment_and_wmatch(
    tmp_path, reference, current,
):
    for result in align_line_breaks(reference, current, width=1000):
        assert result["aligned"] == result["before"]
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    new.write_text(current)
    run([str(old), str(new)], wrapnumber=1000)
    assert new.read_text() == current


def test_removed_hard_break_is_not_restored_by_alignment(tmp_path):
    reference = "First words  \ncontinue here.\n"
    current = "First words continue here.\n"
    (result,) = align_line_breaks(reference, current)
    assert "  \n" not in result["aligned"]
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    new.write_text(current)
    run([str(old), str(new)])
    assert "  \n" not in new.read_text()


@pytest.mark.parametrize("context", ["{}", "Use ${}$ here."])
@pytest.mark.parametrize("before,after", [
    ("alpha,beta", "alpha, beta"),
    ("alpha, beta", "alpha,beta"),
    ("alpha(beta)", "alpha (beta)"),
    ("alpha (beta)", "alpha(beta)"),
    ("alpha:beta", "alpha :beta"),
    ("alpha :beta", "alpha:beta"),
])
def test_alignment_preserves_last_space_everywhere(
    tmp_path, context, before, after,
):
    reference = context.format(before) + "\n"
    current = context.format(after) + "\n"
    for result in align_line_breaks(reference, current):
        assert result["aligned"] == result["before"]
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    new.write_text(current)
    run([str(old), str(new)])
    assert new.read_text() == current


def test_extra_spaces_and_presentation_margins_can_be_cleaned(tmp_path):
    reference = "Keep one separator here.\n"
    current = " Keep   one \t separator here.\n"
    (result,) = align_line_breaks(reference, current, width=79)
    assert result["aligned"] == reference
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    new.write_text(current)
    run([str(old), str(new)])
    assert new.read_text() == reference
    new.write_text(reference.rstrip("\n") + " \n")
    autofix_markdown_file(new, wrapnumber=79)
    assert new.read_text() == reference


def test_cpb_preserves_rendered_spacing_while_restoring_source_breaks(
    tmp_path,
):
    import subprocess

    reference = (
        "A probe inside small RMs\ndispersed in dodecane "
        "($32.9;\\text{kJ}/\\text{mol}$ : @fig:cycle, blue),\nwhich\n"
    )
    current = reference.replace("RMs\ndispersed", "RMs dispersed").replace(
        "$ :", "$:"
    )
    path = tmp_path / "source.md"
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    path.write_text(reference)
    subprocess.run(["git", "-C", str(tmp_path), "add", "source.md"],
                   check=True, capture_output=True)
    path.write_text(current)
    autofix_markdown_file(path, wrapnumber=1000, git_index=True)
    assert path.read_text() == reference.replace("$ :", "$:")


@pytest.mark.parametrize("old_prefix,new_prefix", [
    ("", " "), ("  ", ""), (" ", "   "),
])
@pytest.mark.parametrize("body", ["Stable.\n", "Same words changed here.\n"])
def test_presentation_indentation_restores_matching_line_starts(
    old_prefix, new_prefix, body,
):
    reference = old_prefix + body.replace("changed", "original")
    current = new_prefix + body
    (result,) = align_line_breaks(reference, current, width=79)
    assert result["aligned"] == old_prefix + body
    assert all(
        item["aligned"] == item["before"]
        for item in align_line_breaks(reference, result["aligned"], width=79)
    )


def test_leading_indentation_edits_do_not_overlap_whitespace_restoration():
    reference = "  Same words\n  continue here.\n"
    current = " Same  words\n continue here.\n"
    (result,) = align_line_breaks(reference, current, width=79)
    assert result["aligned"] == reference


@pytest.mark.parametrize("reference,current", [
    ("Code words.\n", "    Code words.\n"),
    ("    Code words.\n", " Code words.\n"),
    ("\tCode words.\n", "Code words.\n"),
    ("- Parent.\n  - Child.\n", "- Parent.\n   - Child.\n"),
    ("- Item.\n\n  Continuation.\n", "- Item.\n\n   Continuation.\n"),
    ("> Quote.\n", " > Quote.\n"),
    ("> First.\n continuation.\n", "> First.\n  continuation.\n"),
    ("```\n Code.\n```\n", "```\n  Code.\n```\n"),
    ("Introduction.\n\n  Indented paragraph.\n",
     "Introduction.\n\n Indented paragraph.\n"),
    ("Introduction.\n\n Indented paragraph.\n",
     "Introduction.\n\n  Indented paragraph.\n"),
])
def test_structural_indentation_is_preserved(reference, current):
    assert all(
        result["aligned"] == result["before"]
        for result in align_line_breaks(reference, current, width=79)
    )


@pytest.mark.parametrize("old_prefix,new_prefix", [
    ("", "    "), ("\t", " "), ("    ", ""),
])
def test_indentation_inside_comment_restores_baseline(old_prefix, new_prefix):
    reference = "<!--\n" + old_prefix + "Hidden words.\n-->\n"
    current = "<!--\n" + new_prefix + "Hidden words.\n-->\n"
    (result,) = align_line_breaks(reference, current, width=79)
    assert (
        current[:result["start"]] + result["aligned"]
        + current[result["stop"]:]
    ) == reference


@pytest.mark.parametrize("reference,current", [
    (
        "<!--same hidden\nwords-->Visible prose.\n",
        "<!--same\nhidden words-->Visible prose.\n",
    ),
    (
        "Intro <!-- hidden note\nwith more words --> finishes here.\n",
        "Intro <!-- hidden\nnote with more words --> finishes here.\n",
    ),
    (
        "<!--\nFirst hidden sentence. Keep this long line as it was.\n-->\n",
        "<!--\nFirst hidden sentence. Keep this long\nline as it was.\n-->\n",
    ),
])
def test_html_comment_alignment_preserves_boundaries(reference, current):
    results = align_line_breaks(reference, current, width=79)
    for result in reversed(results):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference


def test_html_comment_hunk_keeps_context_during_prose_lint():
    reference = (
        "<!-- unchanged opening\n"
        "Hidden sentence. This long commented line must remain intact.\n"
        "-->\nVisible sentence.\nNext visible sentence.\n"
    )
    current = reference.replace("-->\nVisible", "--> Visible").replace(
        "Visible sentence.\nNext", "Visible sentence. Next"
    )
    results = align_line_breaks(reference, current, width=30)
    for result in reversed(results):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference


def test_visible_sentence_fix_ignores_comment_sentence_boundary():
    reference = "Intro <!-- Hidden sentence. Stay here. --> first draft.\n"
    current = (
        "Intro <!-- Hidden sentence. Stay here. --> visible sentence. "
        "Next sentence.\n"
    )
    results = align_line_breaks(reference, current, width=79)
    (result,) = results
    assert result["aligned"] == (
        "Intro <!-- Hidden sentence. Stay here. --> visible sentence.\n"
        "Next sentence.\n"
    )


def test_literal_comment_in_fenced_code_does_not_enable_alignment():
    reference = "```html\n<!-- Hidden words on one line. -->\n```\n"
    current = "```html\n<!-- Hidden words\non one line. -->\n```\n"
    assert all(
        result["aligned"] == result["before"]
        for result in align_line_breaks(reference, current, width=20)
    )


def test_comment_alignment_preserves_reference_whitespace():
    reference = "<!--\nFirst\tstable words \ncontinued here.\n-->\n"
    current = "<!--\nFirst stable\nwords continued here.\n-->\n"
    (result,) = align_line_breaks(reference, current, width=20)
    restored = (
        current[:result["start"]] + result["aligned"]
        + current[result["stop"]:]
    )
    assert restored == reference


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("body", [
    r"$$R_c \approx (100\,\text{nm·K})/\Delta T$$",
    r"$$R_c \approx 100/28 \approx 3.6\,\text{nm}$$",
    "Attached(punctuation),without spaces.",
])
def test_hidden_source_layout_matches_across_attached_punctuation(
    tmp_path, body, ending,
):
    import subprocess

    reference = (
        "Visible prose.\n<!--\nRS: Calculation:\n" + body + "\n-->\n"
        "Visible $x$ (reference): preserve this space.\n"
    ).replace("\n", ending)
    changed_body = body.replace("$$", "$$\n", 1)
    if body.endswith("$$"):
        changed_body = changed_body[:-2] + "\n$$"
    else:
        changed_body = body.replace("(", " ( ").replace(
            "),", " ) ,\n"
        )
    current = reference.replace(body, changed_body.replace("\n", ending))
    restored = current
    for result in reversed(align_line_breaks(reference, current, width=79)):
        restored = (
            restored[:result["start"]] + result["aligned"]
            + restored[result["stop"]:]
        )
    assert restored == reference
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_bytes(reference.encode())
    new.write_bytes(current.encode())
    run([str(old), str(new)])
    # wmatch reads text with universal newline handling.
    assert new.read_text() == reference.replace(ending, "\n")
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    new.write_bytes(reference.encode())
    subprocess.run(["git", "-C", str(tmp_path), "add", "new.md"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name",
                    "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email",
                    "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "Base"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "tag", "jf_last"],
                   check=True)
    new.write_bytes(current.encode())
    autofix_markdown_file(new, wrapnumber=79, git_ref="jf_last")
    assert new.read_bytes() == reference.encode()
    assert not autofix_markdown_file(
        new, wrapnumber=79, git_ref="jf_last",
    )["fixes"]


def test_literal_comment_delimiters_remain_opaque():
    delimiter = "`"
    reference = f"Use {delimiter}<!-- hidden words -->{delimiter} here.\n"
    current = f"Use {delimiter}<!--hidden words-->{delimiter} here.\n"
    assert all(
        result["aligned"] == result["before"]
        for result in align_line_breaks(reference, current, width=79)
    )


@pytest.mark.parametrize("reference,current", [
    (
        r"$$\tau_c= \frac{4\pi\eta r^3}{3 k_B T}$${#eq:SDE}" + "\n",
        "$$\n" + r"\tau_c= \frac{4\pi\eta r^3}{3 k_B T}"
        + "\n$${#eq:SDE}\n",
    ),
    ("$$a + b$$\n", "$$\na +\nb\n$$\n"),
    ("$$\n x = y\n$$\n", "$$\n\t  x = y\n$$\n"),
    ("$$a + " + "b + " * 30 + "c$$\n",
     "$$\na + " + "b + " * 30 + "c\n$$\n"),
    (r"$$r(w_0) = \begin{cases}" + "\n"
     + r"m w_0 + \delta & w_0 < 20 \\[8pt]" + "\n"
     + r"c & w_0 \geq 20\end{cases}$$" + "\n",
     "$$\n" + r"r(w_0) = \begin{cases}" + "\n"
     + r"m w_0 + \delta & w_0 < 20 \\[8pt]" + "\n"
     + r"c & w_0 \geq 20\end{cases}" + "\n$$\n"),
])
def test_math_layout_restores_baseline_without_prose_lint(reference, current):
    for result in reversed(align_line_breaks(reference, current, width=79)):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference


def test_inline_math_changed_value_keeps_edit_and_restores_whitespace():
    reference = "$0.51\\ \\mathrm{mPa}\\cdot\\mathrm{s}$\n"
    current = "$0.506\\\n\\mathrm{mPa}\\cdot\\mathrm{s}$\n"
    (result,) = align_line_breaks(reference, current, width=79)
    assert result["aligned"] == reference.replace("0.51", "0.506")


def test_changed_first_word_still_restores_presentation_indentation():
    reference = "  Old wording stays here.\n"
    current = " New wording stays here.\n"
    (result,) = align_line_breaks(reference, current, width=79)
    assert result["aligned"] == "  New wording stays here.\n"


def test_equation_hunk_starts_inside_display_math():
    reference = "$$\n  a + b = c\n  + d\n$$\nVisible sentence.\n"
    current = reference.replace("  a + b = c\n  + d", "\ta + b = c + d")
    for result in reversed(align_line_breaks(reference, current, width=10)):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference


def test_many_hunks_do_not_reparse_the_whole_document(monkeypatch):
    reference = "".join(
        f"Paragraph {number} has stable reference words\n"
        "and continues on a second line.\n\n"
        for number in range(40)
    )
    current = reference.replace("words\nand", "words and")
    scanned = []
    original = wrap_sentences._markdown_spans

    def record_scans(text, *args, **kwargs):
        scanned.append(len(text))
        return original(text, *args, **kwargs)

    monkeypatch.setattr(wrap_sentences, "_markdown_spans", record_scans)
    results = align_line_breaks(reference, current, width=79)
    assert len(results) == 40
    for result in reversed(results):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference
    # Parsing work stays proportional to document size as hunks accumulate.
    assert sum(scanned) < 20 * len(reference)


@pytest.mark.parametrize("block", [
    "  <!--\nHidden sentence. Stay here.\n\nHidden words\ncontinue.\n-->\n",
    "$$\na = b\n\n  + c\n  + d\n$$\n",
    "```\nLiteral code.\n\nMore literal code.\n```\n",
])
def test_bounded_context_preserves_blocks_with_blank_lines(block):
    reference = "Introductory paragraph.\n\n" + block + "\nFinal paragraph.\n"
    current = reference.replace("words\ncontinue", "words continue").replace(
        "  + c\n  + d", "  + c + d",
    )
    results = align_line_breaks(reference, current, width=25)
    for result in reversed(results):
        current = (
            current[:result["start"]] + result["aligned"]
            + current[result["stop"]:]
        )
    assert current == reference


@pytest.mark.parametrize("text", [
    "```tex\n$$x + y$$\n```\n",
    "    $$x + y$$\n",
    "Use `$$x + y$$` as literal code.\n",
    r"An escaped \$ is ordinary text." + "\n",
])
def test_literal_math_markers_do_not_enable_alignment(text):
    current = text.replace("x + y", "x  + y")
    assert all(
        result["aligned"] == result["before"]
        for result in align_line_breaks(text, current, width=79)
    )


def test_batched_word_diff_keeps_hunks_isolated(monkeypatch):
    reference = (
        "Former introduction\nsame reference words\nformer closing.\n"
        "\nUnchanged anchor.\n\n"
        "Other introduction\nsame reference words\nother closing.\n"
    )
    current = (
        "Changed introduction same reference words changed closing.\n"
        "\nUnchanged anchor.\n\n"
        "Updated introduction same reference words updated closing.\n"
    )
    expected = [
        "Changed introduction\nsame reference words\nchanged closing.\n",
        "Updated introduction\nsame reference words\nupdated closing.\n",
    ]
    calls = []
    original_run = line_alignment.subprocess.run

    def record_diff(command, **options):
        calls.append(Path(command[-1]).read_text())
        return original_run(command, **options)

    monkeypatch.setattr(line_alignment.subprocess, "run", record_diff)
    results = align_line_breaks(reference, current)
    assert [result["aligned"] for result in results] == expected
    assert len(calls) == 2  # one line diff, one isolated batch of word diffs


def test_optional_preservation_break_does_not_strand_a_tiny_fragment():
    reference = (
        "Former introduction\nstable reference words\nformer closing.\n"
    )
    current = "X stable reference words rewritten closing.\n"
    (result,) = align_line_breaks(reference, current)
    # Reference whitespace is restored after "words", but separating "X"
    # just to preserve the next reference line would make a tiny new row.
    assert result["aligned"] == (
        "X stable reference words\nrewritten closing.\n"
    )


@pytest.mark.parametrize("punctuation", [",", ";", ":", ")", "--", "–", "—"])
@pytest.mark.parametrize("distance", [0, 19, 20, 21])
def test_dependent_phrase_lint_applies_below_maximum_width(
    tmp_path,
    punctuation,
    distance,
):
    prefix = "These measurements characterize the dynamics" + punctuation
    width = len(prefix) + 20
    text = prefix + " short phrase.\n"
    assert len(text.rstrip()) < width
    issues = check_prose(text, width, distance)
    expected = prefix + "\nshort phrase.\n" if distance >= 20 else text
    assert bool(issues) == (distance >= 20)
    if issues:
        assert issues[0][1].startswith("trailing dependent phrase:")
    assert wrap_prose(text, width, distance) == expected
    path = tmp_path / "source.md"
    path.write_text(text)
    report = autofix_markdown_file(path, width, distance)
    assert path.read_text() == expected
    assert bool(report["fixes"]) == (distance >= 20)
    assert check_prose(expected, width, distance) == []


def test_dependent_phrase_can_break_before_an_open_parenthesis():
    prefix = "These measurements characterize the dynamics"
    text = prefix + " (a short phrase).\n"
    width = len(prefix) + 20
    assert wrap_prose(text, width) == prefix + "\n(a short phrase).\n"
    assert check_prose(text, width, 20)[0][1].startswith(
        "trailing dependent phrase:"
    )


def test_repeated_word_pair_width_fix_uses_the_reported_column(tmp_path):
    text = "Start " + "extra words " * 20 + "end.\n"
    path = tmp_path / "source.md"
    path.write_text(text)
    autofix_markdown_file(path, wrapnumber=79)
    assert path.read_text() == wrap_prose(text, 79)
    assert len(path.read_text().splitlines()[0]) > 60
