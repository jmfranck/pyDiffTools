"""Desired Git join width and maximum prose width are independent."""

import subprocess

from pydifftools.line_alignment import align_line_breaks
from pydifftools.match_spaces import run
from pydifftools.wrap_sentences import autofix_markdown_file


def test_desired_width_controls_git_joins():
    reference = "These stable words explain the water near an interface.\n"
    current = reference.replace("water near", "water\nnear")
    for desired, expected in [(45, current), (79, reference)]:
        (result,) = align_line_breaks(
            reference, current, width=79, desired_width=desired,
            punctuation_slop=0,
        )
        assert result["aligned"] == expected


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
    current = reference.replace("water near", "water\nnear")
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    for desired, expected in [(45, current), (79, reference)]:
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
    current = reference.replace("water near", "water\nnear")
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(reference)
    env = dict(os.environ)
    env["PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE"] = time.strftime(
        "%Y-%m-%d", time.gmtime(),
    )
    for desired, expected in [(45, current), (79, reference)]:
        new.write_text(current)
        subprocess.run(
            [sys.executable, "-m", "pydifftools.command_line", "wmatch",
             "--desired-width", str(desired), "--wrapnumber", "79",
             "--trailing-dependent-phrase", "0", str(old), str(new)],
            check=True, capture_output=True, env=env,
        )
        assert new.read_text() == expected
