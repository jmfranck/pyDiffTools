"""Terminal review never needs Qt, image helpers, or a GUI editor."""

import curses
import subprocess
from types import SimpleNamespace

import pytest

from pydifftools import git_gd, git_gd_terminal
from pydifftools.git_gd import DiffEntry


@pytest.mark.parametrize("args", [
    ["--terminal", "HEAD", "--", "notes.txt"],
    ["HEAD", "--terminal", "--", "notes.txt"],
])
def test_terminal_dispatch_preserves_git_arguments(monkeypatch, args):
    calls = []
    monkeypatch.setattr(git_gd, "build_entries", lambda args: (
        calls.append(list(args)) or (["HEAD"], [])
    ))
    monkeypatch.setattr(git_gd, "repo_name", lambda: "repo")
    monkeypatch.setattr(git_gd_terminal, "launch_review", lambda *args: 23)
    assert git_gd.main(args) == 23
    assert calls == [["HEAD", "--", "notes.txt"]]


@pytest.mark.parametrize("args", [
    ["--terminal", "HEAD", "--", "--terminal"],
    ["--terminal", "--cached", "--", "notes.txt"],
])
def test_terminal_cli_flag(monkeypatch, args):
    from pydifftools import command_line

    calls = []
    monkeypatch.setattr(git_gd, "main", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(command_line.update_check, "check_update",
                        lambda *args: ("1", "1", False))
    command_line.main(["gd", *args])
    assert calls == [args]


def test_terminal_needs_tty(monkeypatch, capsys):
    monkeypatch.setattr(git_gd_terminal.sys.stdin, "isatty", lambda: False)
    assert git_gd_terminal.launch_review("repo", [], []) == 1
    assert "interactive terminal" in capsys.readouterr().err


@pytest.mark.parametrize("exit_code", [0, 1])
def test_terminal_review_filters_and_opens_vim(monkeypatch, exit_code):
    monkeypatch.setattr(git_gd_terminal.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(git_gd_terminal.sys.stdout, "isatty", lambda: True)
    stats = []
    entries = [
        DiffEntry("photo.png", None, None),
        DiffEntry("vector.svg", 0, 0),
        DiffEntry("archive.bin", None, None),
        DiffEntry("new name.txt", 1, 1, status="R090",
                  old_path="old name.txt", new_path="new name.txt"),
        DiffEntry("added.txt", 0, 0, status="A"),
    ]

    def numstat(args, paths):
        stats.append(paths)
        return (None, None) if paths == ["archive.bin"] else (2, 1)

    monkeypatch.setattr(git_gd_terminal, "numstat_for_paths", numstat)
    keys = iter([curses.KEY_DOWN, 10, curses.KEY_UP, ord(" "), ord("q")])
    drawn = []
    screen = SimpleNamespace(
        keypad=lambda value: None, erase=lambda: None,
        getmaxyx=lambda: (20, 100),
        addnstr=lambda *args: drawn.append(args), refresh=lambda: None,
        getch=lambda: next(keys), clearok=lambda value: None,
    )
    restored = []
    monkeypatch.setattr(curses, "wrapper", lambda callback: callback(screen))
    monkeypatch.setattr(curses, "curs_set", lambda value: None)
    monkeypatch.setattr(curses, "has_colors", lambda: False)
    monkeypatch.setattr(curses, "def_prog_mode", lambda: None)
    monkeypatch.setattr(curses, "endwin", lambda: None)
    monkeypatch.setattr(curses, "reset_prog_mode",
                        lambda: restored.append(True))
    commands = []
    monkeypatch.setattr(git_gd_terminal.subprocess, "run", lambda cmd: (
        commands.append(cmd) or subprocess.CompletedProcess(cmd, exit_code)
    ))
    assert git_gd_terminal.launch_review("repo", ["--cached"], entries) == 0
    assert stats == [["archive.bin"], ["old name.txt", "new name.txt"],
                     ["added.txt"]]
    assert len(commands) == 1
    command = commands[0]
    assert 'vim -f -d -- "$LOCAL" "$REMOTE"' in command[2]
    assert command[-4:] == ["--cached", "--", "old name.txt", "new name.txt"]
    assert entries[3].seen is (exit_code == 0)
    assert entries[4].seen
    assert restored == [True]
    assert any("3 images/binary skipped" in row[2] for row in drawn)
