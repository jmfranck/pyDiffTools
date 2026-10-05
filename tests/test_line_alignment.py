"""Regression cases for the shared word/whitespace alignment pipeline."""

import pytest
from pathlib import Path

from pydifftools.line_alignment import align_line_breaks, minimal_opcodes
from pydifftools import line_alignment
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
