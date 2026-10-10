"""Real Git branch updates, alias dispatch, and cached completion."""

import argparse
import io
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pydifftools import command_line
from pydifftools.git_aliases import mergein_completer


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def remote_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.delenv("GIT_PREFIX", raising=False)
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    git("init", "--bare", "--initial-branch=current", str(remote))
    git("init", "--initial-branch=current", str(seed))
    git("config", "user.name", "Test Author", cwd=seed)
    git("config", "user.email", "test@example.invalid", cwd=seed)
    (seed / "shared.txt").write_text("baseline\n")
    git("add", "shared.txt", cwd=seed)
    git("commit", "-m", "Baseline", cwd=seed)
    git("remote", "add", "origin", str(remote), cwd=seed)
    git("checkout", "-b", "incoming/topic", cwd=seed)
    (seed / "shared.txt").write_text("incoming\n")
    git("commit", "-am", "Incoming", cwd=seed)
    git("push", "origin", "current", "incoming/topic", cwd=seed)
    git("clone", str(remote), str(work))
    monkeypatch.chdir(work)
    git("config", "user.name", "Test Author")
    git("config", "user.email", "test@example.invalid")
    return seed


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("remote", ["origin", "upstream"])
def test_mergein_updates_branch_and_creates_merge(
    remote_project, existing, remote,
):
    before = git("rev-parse", "HEAD")
    if existing:
        git("branch", "incoming/topic", "origin/incoming/topic")
    if remote != "origin":
        git("remote", "rename", "origin", remote)
    (remote_project / "new.txt").write_text("new remote commit\n")
    git("add", "new.txt", cwd=remote_project)
    git("commit", "-m", "Advance incoming", cwd=remote_project)
    git("push", "origin", "incoming/topic", cwd=remote_project)
    incoming = git("rev-parse", "HEAD", cwd=remote_project)
    args = ["mergein", "incoming/topic"]
    if remote != "origin":
        args += ["--remote", remote]
    command_line.main(args)
    assert git("branch", "--show-current") == "current"
    assert git("rev-parse", "incoming/topic") == incoming
    assert git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:] == [
        before, incoming,
    ]
    assert Path("new.txt").read_text() == "new remote commit\n"


@pytest.mark.parametrize("failure", ["missing", "diverged", "checked_out"])
def test_fetch_failure_does_not_merge(remote_project, failure):
    branch = "incoming/topic"
    if failure == "missing":
        branch = "missing"
    elif failure == "diverged":
        git("branch", branch)
        git("checkout", branch)
        Path("local.txt").write_text("local incoming work\n")
        git("add", "local.txt")
        git("commit", "-m", "Local incoming work")
        git("checkout", "current")
    else:
        git("checkout", "-b", branch)
    before = git("rev-parse", "HEAD")
    with pytest.raises(SystemExit) as exc:
        command_line.main(["mergein", branch])
    assert exc.value.code != 0
    assert git("rev-parse", "HEAD") == before
    assert not Path(".git/MERGE_HEAD").exists()


def test_merge_conflict_preserves_git_state(remote_project):
    Path("shared.txt").write_text("current branch change\n")
    git("commit", "-am", "Current change")
    before = git("rev-parse", "HEAD")
    with pytest.raises(SystemExit) as exc:
        command_line.main(["mergein", "incoming/topic"])
    assert exc.value.code == 1
    assert git("rev-parse", "HEAD") == before
    assert Path(".git/MERGE_HEAD").read_text().strip() == git(
        "rev-parse", "incoming/topic",
    )
    assert "UU shared.txt" in git("status", "--short")


def test_installed_alias_forwards_remote_and_branch(
    remote_project, tmp_path, monkeypatch,
):
    git("remote", "rename", "origin", "upstream")
    launcher = tmp_path / "pydifft"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "from pydifftools.command_line import main\nmain()\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    command_line.main(["--add_to_git", "mergein"])
    git("mergein", "--remote", "upstream", "incoming/topic")
    assert git("branch", "--show-current") == "current"
    assert Path("shared.txt").read_text() == "incoming\n"


@pytest.mark.parametrize("args", [
    ["--add_to_git"],
    ["--add_to_git", "gd", "unknown"],
    ["--add_to_git", "gd", "--", "tree"],
    ["pd", "--add-to-git"],
    ["tree", "--install"],
])
def test_invalid_installer_does_not_write(remote_project, args):
    with pytest.raises(SystemExit) as exc:
        command_line.main(args)
    assert exc.value.code == 2
    assert not Path(os.environ["GIT_CONFIG_GLOBAL"]).exists()


def test_multiple_installs_and_completion_location(
    remote_project, tmp_path, monkeypatch, capsys,
):
    completion_root = tmp_path / "custom completion directory"
    monkeypatch.setenv("BASH_COMPLETION_USER_DIR", str(completion_root))
    command_line.main(["--add_to_git", "gd", "pd", "tree", "mergein"])
    for name in ("gd", "pd", "tree", "mergein"):
        assert "pydifft " + name in git(
            "config", "--global", "--get", "alias." + name,
        )
    assert "_git_mergein" in (
        completion_root / "completions/git-mergein"
    ).read_text()
    assert "difftool.mygvim.cmd" in capsys.readouterr().out
    help_text = command_line.build_parser().format_help()
    assert "--add_to_git" in help_text.split("commands:", 1)[1]


def test_cached_python_completion_filters_remote_refs(remote_project):
    git("branch", "local-only")
    git("update-ref", "refs/remotes/other/other-only", "HEAD")
    branch = argparse.Namespace(dest="branch")
    remote = argparse.Namespace(dest="remote")
    parsed = argparse.Namespace(remote="origin")
    assert mergein_completer("in", parsed, action=branch) == [
        "incoming/topic",
    ]
    assert "HEAD" not in mergein_completer("", parsed, action=branch)
    parsed.remote = "other"
    assert mergein_completer("", parsed, action=branch) == ["other-only"]
    parsed.remote = "missing"
    assert mergein_completer("", parsed, action=branch) == []
    assert mergein_completer("or", parsed, action=remote) == ["origin"]


@pytest.mark.parametrize("line,expected", [
    ("pydifft mergein in", ["incoming/topic"]),
    ("pydifft mergein --remote other oth", ["other-only"]),
    ("pydifft mergein --remote or", ["origin"]),
])
def test_argcomplete_mergein(remote_project, monkeypatch, line, expected):
    argcomplete = pytest.importorskip("argcomplete")
    from argcomplete import io as argcomplete_io

    monkeypatch.setattr(
        argcomplete.CompletionFinder, "_init_debug_stream", lambda self: None,
    )
    monkeypatch.setattr(argcomplete_io, "debug_stream", io.StringIO())
    git("update-ref", "refs/remotes/other/other-only", "HEAD")
    monkeypatch.setenv("_ARGCOMPLETE", "1")
    monkeypatch.setenv("_ARGCOMPLETE_IFS", "\013")
    monkeypatch.setenv("COMP_LINE", line)
    monkeypatch.setenv("COMP_POINT", str(len(line)))
    output = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        argcomplete.autocomplete(
            command_line.build_parser(), always_complete_options=False,
            exit_method=sys.exit, output_stream=output,
        )
    assert exc.value.code == 0
    assert [name.strip() for name in output.getvalue().split("\013")] == (
        expected
    )


@pytest.mark.parametrize("branch", ["invalid:branch", "-option", "@{-1}"])
def test_invalid_branch_does_not_fetch(remote_project, branch):
    before = git("rev-parse", "HEAD")
    with pytest.raises(SystemExit, match="invalid branch name"):
        command_line.main(["mergein", "--", branch])
    assert git("rev-parse", "HEAD") == before
    assert not Path(".git/FETCH_HEAD").exists()


@pytest.mark.parametrize("words,expected", [
    (["git", "mergein", "in"], "incoming/topic"),
    (["git", "mergein", "--remote", "other", "oth"], "other-only"),
    (["git", "mergein", "--remote=other", "oth"], "other-only"),
    (["git", "mergein", "--remote", "or"], "origin"),
    (["git", "mergein", "--remote=or"], "--remote=origin"),
    (["git", "mergein", "--remote", "missing", ""], ""),
    (["git", "mergein", "incoming/topic", ""], ""),
])
def test_bash_completion_is_loaded_by_git(
    remote_project, words, expected,
):
    bash_completion = Path("/usr/share/bash-completion/bash_completion")
    if not bash_completion.exists():
        pytest.skip("system Bash completion is unavailable")
    git("update-ref", "refs/remotes/other/other-only", "HEAD")
    command_line.main(["--add_to_git", "mergein"])
    # Arguments cross into Bash via positional parameters, not shell quoting.
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", """
source /usr/share/bash-completion/bash_completion
_completion_loader git
COMP_WORDS=("$@")
COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
COMP_LINE="${COMP_WORDS[*]}"
COMP_POINT=${#COMP_LINE}
__git_wrap__git_main
printf '%s\n' "${COMPREPLY[@]}"
""", "completion-test", *words],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == expected
