"""Helpers behind ``pydifft gd``.

Install the matching git alias automatically with::

    pydifft gd --install

or manually with::

    git config --global alias.gd '!f() { pydifft gd "$@"; }; f'

This command shells out to ``git difftool --tool=mygvim``, so keep
``difftool.mygvim.cmd`` configured in your git config.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .command_registry import register_command

INSTALL_ALIAS_VALUE = '!f() { pydifft gd "$@"; }; f'


@dataclass
class DiffEntry:
    path: str
    added: int | None
    deleted: int | None
    seen: bool = False

    @property
    def total(self) -> int:
        if self.added is None or self.deleted is None:
            return -1
        return self.added + self.deleted


def git_bytes(args: Sequence[str]) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True
    ).stdout


def split_diff_args(argv: Sequence[str]):
    if "--" in argv:
        split_idx = argv.index("--")
        return list(argv[:split_idx]), list(argv[split_idx + 1 :])
    return list(argv), []


def changed_paths(
    diff_args: Sequence[str], pathspec: Sequence[str]
) -> list[str]:
    cmd = ["diff", "--name-only", "-z", *diff_args]
    if pathspec:
        cmd += ["--", *pathspec]
    data = git_bytes(cmd)
    return [os.fsdecode(x) for x in data.split(b"\x00") if x]


def numstat_for_path(diff_args: Sequence[str], path: str):
    cmd = ["git", "diff", "--numstat", *diff_args, "--", path]
    out = subprocess.run(
        cmd, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    if not out:
        return (0, 0)
    first = out[0].split("\t")
    if len(first) < 2:
        return (0, 0)
    try:
        added = int(first[0])
    except ValueError:
        added = None
    try:
        deleted = int(first[1])
    except ValueError:
        deleted = None
    return (added, deleted)


def repo_name() -> str:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(top).name


def build_entries(argv: Sequence[str]):
    diff_args, pathspec = split_diff_args(argv)
    paths = changed_paths(diff_args, pathspec)
    entries: list[DiffEntry] = []
    for path in paths:
        added, deleted = numstat_for_path(diff_args, path)
        entries.append(DiffEntry(path=path, added=added, deleted=deleted))
    entries.sort(
        key=lambda x: (
            -((x.added or 0) + (x.deleted or 0)),
            -(x.added or 0),
            -(x.deleted or 0),
            x.path,
        )
    )
    return diff_args, entries


def install_alias() -> None:
    subprocess.run(
        ["git", "config", "--global", "alias.gd", INSTALL_ALIAS_VALUE],
        check=True,
    )
    print("Installed global git alias: alias.gd -> pydifft gd")
    tool_cmd = subprocess.run(
        ["git", "config", "--global", "--get", "difftool.mygvim.cmd"],
        capture_output=True,
        text=True,
    )
    if tool_cmd.returncode != 0 or not tool_cmd.stdout.strip():
        print(
            "Reminder: configure difftool.mygvim.cmd so git difftool knows "
            "which GUI diff tool to launch."
        )


def main(argv: Sequence[str]) -> int:
    try:
        diff_args, entries = build_entries(argv)
        name = repo_name()
    except subprocess.CalledProcessError as exc:
        if isinstance(exc.stderr, bytes):
            sys.stderr.buffer.write(exc.stderr)
        elif exc.stderr:
            sys.stderr.write(exc.stderr)
        return exc.returncode
    try:
        from .git_gd_qt import launch_review
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise RuntimeError(
                "pydifft gd requires PySide6. Install PySide6, then rerun "
                "the command."
            ) from exc
        raise
    return launch_review(name, diff_args, entries)


@register_command(
    "review changed files in a Qt table before launching git difftool",
    "review changed files in a Qt table before launching git difftool\n\n"
    "\n"
    "Install the matching git alias automatically with:\n"
    "  pydifft gd --install\n\n"
    "or add it yourself with:\n"
    "  git config --global alias.gd '!f() { pydifft gd \"$@\"; }; f'\n\n"
    "This command shells out to git difftool --tool=mygvim, so keep\n"
    "difftool.mygvim.cmd configured in your git config.",
    help={
        "install": "Install or update the global git alias so `git gd` "
        "runs this subcommand.",
    },
)
def gd(arguments, install=False):
    """Mirror ``git_gd_qt.py`` and optionally install ``git gd``."""

    if install:
        if arguments:
            raise SystemExit("pydifft gd --install does not take diff args")
        install_alias()
        return
    return_code = main(arguments)
    if return_code != 0:
        raise SystemExit(return_code)
