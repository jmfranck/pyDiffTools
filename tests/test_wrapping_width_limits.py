"""Desired Git join width and maximum prose width are independent."""

import subprocess

from pydifftools.line_alignment import align_line_breaks
from pydifftools.match_spaces import run
from pydifftools.wrap_sentences import autofix_markdown_file


def test_desired_width_controls_git_joins_where_words_differ():
    reference = "These stable words explain the water near an interface.\n"
    current = reference.replace("stable", "edited").replace(
        "water near", "water\nnear",
    )
    for desired, expected in [
        (45, current), (79, reference.replace("stable", "edited")),
    ]:
        (result,) = align_line_breaks(
            reference, current, width=79, desired_width=desired,
            punctuation_slop=0,
        )
        assert result["aligned"] == expected


def test_whitespace_only_change_always_restores_reference():
    """When matching the reference's free whitespace removes the diff, the
    reference layout is kept, however wide, up to the hard width."""
    reference = "These stable words explain the water near an interface.\n"
    current = reference.replace("water near", "water\nnear")
    for desired in (20, 45, 79):
        (result,) = align_line_breaks(
            reference, current, width=79, desired_width=desired,
            punctuation_slop=0,
        )
        assert result["aligned"] == reference
    # past the hard width, the line may be rewrapped after all
    (result,) = align_line_breaks(
        reference, current, width=40, desired_width=20, punctuation_slop=0,
    )
    assert result["aligned"] != reference
    assert max(map(len, result["aligned"].splitlines())) <= 40


def test_caption_line_at_exactly_the_hard_width_matches_reference():
    # from a manuscript caption: the only difference from the baseline was
    # a line break, and the joined baseline line is exactly 79 characters
    reference = (
        "![Temperature dependence of the rotational correlation time of\n"
        "spin probes in small ($w_0=3$ -- indicated in blue for both"
        " subplots) and large\n"
        "($w_0=20$ -- indicated in orange and/or green for both subplots)\n"
        "RMs during cooling and subsequent reheating.\n"
        "**(a)** RMs loaded with ??&nbsp;mM TEMPO-SO~4~ in water and"
        " dispersed in\n"
        "isooctane:\n"
    )
    current = reference.replace("small ($w_0", "small\n($w_0").replace(
        "??&nbsp;mM TEMPO-SO~4~ in", "5&nbsp;mM TEMPO-SO~4~\nin",
    )
    aligned = "".join(
        result["aligned"] for result in align_line_breaks(
            reference, current, width=79, desired_width=45,
            punctuation_slop=20,
        )
    )
    assert (
        "spin probes in small ($w_0=3$ -- indicated in blue for both"
        " subplots) and large\n"
    ) in aligned


def test_general_width_applies_to_stable_git_prose(tmp_path):
    source = "These ordinary words describe the water near an interface " \
        "and explain its behavior in detail.\n"
    path = tmp_path / "source.md"
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    path.write_text(source)
    subprocess.run(["git", "-C", str(tmp_path), "add", path.name],
                   check=True, capture_output=True)
    autofix_markdown_file(
        path, wrapnumber=100, desired_width=45, punctuation_slop=0,
        git_index=True,
    )
    assert path.read_text() == source
    autofix_markdown_file(
        path, wrapnumber=79, desired_width=45, punctuation_slop=0,
        git_index=True,
    )
    assert path.read_text().split() == source.split()
    assert max(map(len, path.read_text().splitlines())) <= 79


def test_wmatch_passes_desired_width(tmp_path):
    reference = "These stable words explain the water near an interface.\n"
    current = reference.replace("stable", "edited").replace(
        "water near", "water\nnear",
    )
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    for desired, expected in [
        (45, current), (79, reference.replace("stable", "edited")),
    ]:
        new.write_text(current)
        run([str(old), str(new)], 79, 0, desired)
        assert new.read_text() == expected


def test_screenshot_breaks_survive_git_restoration():
    reference = (
        "can be explained by modeling the water as a core of bulk-like "
        "water and an interface of altered water.\n"
    )
    current = (
        "can be explained by modeling the water as a\n"
        "core of bulk-like water and an interface of\n"
        "altered water.\n"
    )
    (result,) = align_line_breaks(
        reference, current, width=79, punctuation_slop=0,
    )
    assert result["aligned"] == current


def test_cli_width_arguments_are_independent(tmp_path):
    import os
    import sys
    import time

    reference = "These stable words explain the water near an interface.\n"
    current = reference.replace("stable", "edited").replace(
        "water near", "water\nnear",
    )
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    env = dict(os.environ)
    env["PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE"] = time.strftime(
        "%Y-%m-%d", time.gmtime(),
    )
    for desired, expected in [
        (45, current), (79, reference.replace("stable", "edited")),
    ]:
        new.write_text(current)
        subprocess.run(
            [sys.executable, "-m", "pydifftools.command_line", "wmatch",
             "--desired-width", str(desired), "--wrapnumber", "79",
             "--trailing-dependent-phrase", "0", str(old), str(new)],
            check=True, capture_output=True, env=env,
        )
        assert new.read_text() == expected
