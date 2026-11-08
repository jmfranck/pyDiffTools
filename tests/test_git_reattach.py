"""Reattachment against real repositories, including remote-only branches."""

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pydifftools.git_reattach import reattach
from pydifftools import command_line


def git(path, *args):
    return subprocess.check_output(
        ["git", "-C", str(path), *map(str, args)],
        stderr=subprocess.STDOUT, text=True,
    ).strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work space"
    git(tmp_path, "init", "--bare", "--initial-branch=main", remote)
    git(tmp_path, "clone", remote, seed)
    (seed / "file").write_text("main\n")
    git(seed, "add", "file")
    git(seed, "commit", "-m", "main")
    git(seed, "checkout", "-b", "work/topic")
    (seed / "file").write_text("topic\n")
    git(seed, "commit", "-am", "topic")
    git(seed, "push", "origin", "main", "work/topic")
    git(tmp_path, "clone", remote, work)
    git(work, "checkout", "--detach", "origin/work/topic")
    return seed, work


def test_remote_only_match_tracks_and_preserves_files(project):
    _, work = project
    before = git(work, "rev-parse", "HEAD")
    (work / "file").write_text("uncommitted edit\n")
    (work / "untracked").write_text("keep\n")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == "work/topic"
    assert git(work, "rev-parse", "--abbrev-ref", "@{upstream}") == (
        "origin/work/topic"
    )
    assert git(work, "rev-parse", "HEAD") == before
    assert (work / "file").read_text() == "uncommitted edit\n"
    assert (work / "untracked").read_text() == "keep\n"
    reattach(str(work))
    assert git(work, "rev-parse", "HEAD") == before


def test_local_match_and_dry_run(project):
    _, work = project
    git(work, "branch", "topic-local", "HEAD")
    reattach(str(work), dry_run=True)
    assert git(work, "branch", "--show-current") == ""
    reattach(str(work))
    assert git(work, "branch", "--show-current") == "topic-local"


def test_origin_default_disambiguates_local_branches(project):
    _, work = project
    git(work, "checkout", "--detach", "origin/main")
    git(work, "branch", "alternative", "HEAD")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == "main"


def test_default_remote_branch_wins_over_other_remote_matches(project):
    _, work = project
    git(work, "checkout", "--detach", "origin/main")
    git(work, "branch", "-D", "main")
    git(work, "update-ref", "refs/remotes/origin/alternative", "HEAD")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == "main"
    assert git(work, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"


def test_ambiguous_remote_matches_are_not_chosen_arbitrarily(project, capsys):
    _, work = project
    git(work, "update-ref", "refs/remotes/origin/also-topic", "HEAD")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == ""
    assert "ambiguous" in capsys.readouterr().out


def test_existing_local_branch_is_never_reset(project, capsys):
    _, work = project
    git(work, "branch", "work/topic", "origin/main")
    before = git(work, "rev-parse", "work/topic")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == ""
    assert git(work, "rev-parse", "work/topic") == before
    assert "points elsewhere" in capsys.readouterr().out


def test_no_match_stays_at_recorded_commit(project):
    _, work = project
    (work / "file").write_text("unpublished\n")
    git(work, "commit", "-am", "unpublished")
    before = git(work, "rev-parse", "HEAD")
    reattach(str(work))
    assert git(work, "branch", "--show-current") == ""
    assert git(work, "rev-parse", "HEAD") == before


def test_non_origin_remote_and_branch_with_slash(project):
    _, work = project
    git(work, "remote", "rename", "origin", "upstream")
    reattach(str(work))
    assert git(work, "rev-parse", "--abbrev-ref", "@{u}") == (
        "upstream/work/topic"
    )


def test_recursive_submodule_and_cli_registration(project, tmp_path):
    seed, work = project
    parent = tmp_path / "parent"
    git(tmp_path, "init", "--initial-branch=main", parent)
    git(parent, "-c", "protocol.file.allow=always", "submodule", "add",
        str(seed), "child with spaces")
    child = parent / "child with spaces"
    git(child, "checkout", "--detach", "origin/work/topic")
    git(child, "branch", "-D", "work/topic")
    git(parent, "commit", "-am", "child")
    args = command_line.build_parser().parse_args(
        ["reattach", "--path", str(parent)]
    )
    args._handler(path=args.path, no_recursive=args.no_recursive,
                  fetch=args.fetch, dry_run=args.dry_run)
    assert git(child, "branch", "--show-current") == "work/topic"
    assert git(parent, "branch", "--show-current") == "main"
    assert git(child, "rev-parse", "HEAD") == git(work, "rev-parse", "HEAD")


def test_checked_out_branch_elsewhere_is_not_stolen(project, tmp_path):
    _, work = project
    git(work, "branch", "topic-local", "HEAD")
    git(work, "worktree", "add", tmp_path / "other", "topic-local")
    with pytest.raises(SystemExit):
        reattach(str(work))
    assert git(work, "branch", "--show-current") == ""


def test_fetch_finds_remote_only_match(project):
    _, work = project
    git(work, "update-ref", "-d", "refs/remotes/origin/work/topic")
    reattach(str(work), fetch=True)
    assert git(work, "branch", "--show-current") == "work/topic"
    assert git(work, "rev-parse", "--abbrev-ref", "@{u}") == (
        "origin/work/topic"
    )


def test_installed_git_alias_forwards_options(project, tmp_path, monkeypatch):
    _, work = project
    launcher = tmp_path / "pydifft"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "from pydifftools.command_line import main\nmain()\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    monkeypatch.chdir(work)
    command_line.main(["--add_to_git", "reattach"])
    git(work, "reattach", "--dry-run", "--no-recursive")
    assert git(work, "branch", "--show-current") == ""
    git(work, "reattach", "--no-recursive")
    assert git(work, "branch", "--show-current") == "work/topic"
