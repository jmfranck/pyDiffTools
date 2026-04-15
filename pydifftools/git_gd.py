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
DIFFTOOL_NAME = "mygvim"
RENAME_DIFFTOOL_NAME = "pydifft-gd-rename"


@dataclass
class DiffEntry:
    path: str
    added: int | None
    deleted: int | None
    seen: bool = False
    status: str = ""
    old_path: str | None = None
    new_path: str | None = None

    @property
    def total(self) -> int:
        if self.added is None or self.deleted is None:
            return -1
        return self.added + self.deleted

    @property
    def is_rename(self) -> bool:
        return (
            self.status.startswith("R")
            and self.old_path is not None
            and self.new_path is not None
        )

    @property
    def rename_score(self) -> int | None:
        if not self.is_rename:
            return None
        try:
            return int(self.status[1:])
        except ValueError:
            return None

    @property
    def is_exact_rename(self) -> bool:
        return self.rename_score == 100

    @property
    def diff_paths(self) -> list[str]:
        if self.is_rename:
            assert self.old_path is not None
            assert self.new_path is not None
            return [self.old_path, self.new_path]
        return [self.path]

    @property
    def display_path(self) -> str:
        if not self.is_rename:
            return self.path
        assert self.old_path is not None
        assert self.new_path is not None
        if self.is_exact_rename:
            return f"{self.old_path} → {self.new_path}"
        return f"{self.old_path}\n  → {self.new_path}"

    @property
    def has_multiline_display_path(self) -> bool:
        return "\n" in self.display_path


def git_bytes(args: Sequence[str]) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True
    ).stdout


def split_diff_args(argv: Sequence[str]):
    if "--" in argv:
        split_idx = argv.index("--")
        return list(argv[:split_idx]), list(argv[split_idx + 1 :])
    return list(argv), []


def diff_args_with_renames(diff_args: Sequence[str]) -> list[str]:
    for arg in diff_args:
        if (
            arg == "-M"
            or arg.startswith("-M")
            or arg == "--find-renames"
            or arg.startswith("--find-renames=")
            or arg == "--no-renames"
        ):
            return list(diff_args)
    return [*diff_args, "--find-renames"]


def name_status_entries(
    diff_args: Sequence[str], pathspec: Sequence[str]
) -> list[DiffEntry]:
    cmd = ["diff", "--name-status", "-z", *diff_args_with_renames(diff_args)]
    if pathspec:
        cmd += ["--", *pathspec]
    data = git_bytes(cmd)
    fields = [x for x in data.split(b"\x00") if x]
    entries: list[DiffEntry] = []
    idx = 0
    while idx < len(fields):
        status = os.fsdecode(fields[idx])
        idx += 1
        if status.startswith(("R", "C")):
            old_path = os.fsdecode(fields[idx])
            new_path = os.fsdecode(fields[idx + 1])
            idx += 2
            if status.startswith("C"):
                entries.append(
                    DiffEntry(path=new_path, added=0, deleted=0, status=status)
                )
                continue
            entries.append(
                DiffEntry(
                    path=new_path,
                    added=0,
                    deleted=0,
                    status=status,
                    old_path=old_path,
                    new_path=new_path,
                )
            )
        else:
            path = os.fsdecode(fields[idx])
            idx += 1
            entries.append(
                DiffEntry(path=path, added=0, deleted=0, status=status)
            )
    return entries


def pathspec_changed_paths(
    diff_args: Sequence[str], pathspec: Sequence[str]
) -> set[str]:
    cmd = ["diff", "--name-only", "-z", *diff_args_with_renames(diff_args)]
    if pathspec:
        cmd += ["--", *pathspec]
    data = git_bytes(cmd)
    return {os.fsdecode(x) for x in data.split(b"\x00") if x}


def changed_entries(
    diff_args: Sequence[str], pathspec: Sequence[str]
) -> list[DiffEntry]:
    entries = name_status_entries(diff_args, [])
    if not pathspec:
        return entries
    scoped_paths = pathspec_changed_paths(diff_args, pathspec)
    return [
        entry
        for entry in entries
        if any(path in scoped_paths for path in entry.diff_paths)
    ]


def changed_paths(
    diff_args: Sequence[str], pathspec: Sequence[str]
) -> list[str]:
    return [entry.path for entry in changed_entries(diff_args, pathspec)]


def numstat_for_paths(diff_args: Sequence[str], paths: Sequence[str]):
    cmd = [
        "diff",
        "--numstat",
        "-z",
        *diff_args_with_renames(diff_args),
        "--",
        *paths,
    ]
    data = git_bytes(cmd)
    if not data:
        return (0, 0)
    first = data.split(b"\t", 2)
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


def numstat_for_path(diff_args: Sequence[str], path: str):
    return numstat_for_paths(diff_args, [path])


def configured_difftool_command(tool_name: str = DIFFTOOL_NAME) -> str | None:
    tool_cmd = subprocess.run(
        ["git", "config", "--get", f"difftool.{tool_name}.cmd"],
        capture_output=True,
        text=True,
    )
    if tool_cmd.returncode != 0:
        return None
    return tool_cmd.stdout.strip() or None


def build_difftool_command(
    diff_args: Sequence[str],
    entry: DiffEntry,
    tool_cmd: str | None = None,
) -> list[str]:
    tool_name = DIFFTOOL_NAME
    prefix = ["git"]
    if entry.is_rename:
        if tool_cmd is None:
            tool_cmd = configured_difftool_command()
        if tool_cmd is not None:
            tool_name = RENAME_DIFFTOOL_NAME
            prefix.extend(
                [
                    "-c",
                    (
                        f"difftool.{tool_name}.cmd="
                        f'MERGED="$REMOTE"; {tool_cmd}'
                    ),
                ]
            )

    return [
        *prefix,
        "difftool",
        f"--tool={tool_name}",
        "--no-prompt",
        "--find-renames",
        *diff_args,
        "--",
        *entry.diff_paths,
    ]


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
    entries = changed_entries(diff_args, pathspec)
    for entry in entries:
        entry.added, entry.deleted = numstat_for_paths(
            diff_args, entry.diff_paths
        )
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
