"""Rearrange TeX files according to a plan file."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import List, Sequence


S_CMD = re.compile(
    r"""^s
         /((?:\\.|[^/])*)   # pattern
         /((?:\\.|[^/])*)   # replacement
         /([gi]{0,2})$      # flags
    """,
    re.VERBOSE,
)


def unescape_slashes(s: str) -> str:
    return s.replace(r"\/", "/")


def apply_s_cmd(line: str, cmd: str):
    m = S_CMD.match(cmd)
    if not m:
        raise ValueError(f"Bad s/// command: {cmd!r}")
    pat_raw, rep_raw, flags = m.groups()
    pat = unescape_slashes(pat_raw)
    rep = unescape_slashes(rep_raw)
    reflags = re.IGNORECASE if "i" in flags else 0
    count = 0 if "g" in flags else 1
    # Use re.subn so callers can tell whether the substitution matched any text.
    result, replaced = re.subn(pat, rep, line, count=count, flags=reflags)
    return result, replaced


def parse_plan_line(s: str):
    s = s.rstrip("\n")
    if not s.strip():
        return ("comment", "")
    stripped = s.lstrip()
    if stripped.startswith("#"):
        return ("comment", stripped[1:].strip())
    line = stripped
    idx = 0
    while idx < len(line) and not line[idx].isspace():
        idx += 1
    line_token = line[:idx]
    # Allow plans to specify either a single source line or an inclusive range like "10-20".
    if "-" in line_token:
        range_parts = line_token.split("-")
        if len(range_parts) != 2:
            raise ValueError(f"Bad line range in plan: {line_token!r}")
        start = int(range_parts[0])
        end = int(range_parts[1])
        if end < start:
            raise ValueError(f"Line range out of order: {line_token!r}")
        line_numbers = list(range(start, end + 1))
    else:
        line_numbers = [int(line_token)]
    scratch = False
    s_cmds = []
    pos = idx
    # Walk the remainder of the line manually so spaces inside s/// survive tokenization.
    while pos < len(line):
        while pos < len(line) and line[pos].isspace():
            pos += 1
        if pos >= len(line):
            break
        if line[pos : pos + 7].lower() == "scratch" and (
            pos + 7 == len(line) or line[pos + 7].isspace()
        ):
            scratch = True
            pos += 7
            continue
        if line.startswith("s/", pos):
            start = pos
            pos += 2
            slash_count = 0
            while pos < len(line):
                ch = line[pos]
                if ch == "\\":
                    pos += 2
                    continue
                if ch == "/":
                    slash_count += 1
                    pos += 1
                    if slash_count == 2:
                        while pos < len(line) and line[pos] in "gi":
                            pos += 1
                        cmd = line[start:pos]
                        if not S_CMD.match(cmd):
                            raise ValueError(f"Bad token in plan: {cmd!r}")
                        s_cmds.append(cmd)
                        break
                    continue
                pos += 1
            else:
                raise ValueError(f"Unterminated s/// command in plan: {line!r}")
            continue
        end = pos
        while end < len(line) and not line[end].isspace():
            end += 1
        bad = line[pos:end]
        raise ValueError(f"Bad token in plan: {bad!r}")
    return ("directive", line_numbers, scratch, s_cmds)


def run(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pydifftools rearrange", description="Rearrange TeX file lines"
    )
    parser.add_argument(
        "tex_path", type=pathlib.Path, help="TeX file (modified in place)"
    )
    parser.add_argument(
        "plan_path", type=pathlib.Path, help="Rearrangement plan file (.rrng)"
    )
    args = parser.parse_args(argv)

    tex_lines = args.tex_path.read_text(encoding="utf-8").splitlines(keepends=False)
    n = len(tex_lines)

    items = []
    used: List[int] = []
    with args.plan_path.open("r", encoding="utf-8") as f:
        for raw in f:
            kind, *rest = parse_plan_line(raw)
            if kind == "comment":
                items.append(("comment", rest[0]))
            else:
                line_numbers, scratch, s_cmds = rest
                for ln in line_numbers:
                    if not (1 <= ln <= n):
                        raise ValueError(f"Line number {ln} out of range 1..{n}")
                items.append(("directive", line_numbers, scratch, s_cmds))
                used.extend(line_numbers)

    missing = sorted(set(range(1, n + 1)) - set(used))
    dupes = sorted([x for x in set(used) if used.count(x) > 1])
    if missing:
        sys.exit(f"ERROR: Plan missing lines: {missing}")
    if dupes:
        sys.exit(f"ERROR: Plan duplicated lines: {dupes}")

    out_main: List[str] = []
    out_scratch: List[str] = []
    for it in items:
        if it[0] == "comment":
            out_main.append("% " + it[1])
            continue
        _, line_numbers, scratch, s_cmds = it
        # Track how many replacements each substitution performs across the
        # referenced lines so we can surface errors when a pattern never
        # matches.  This mirrors the Perl s/// behavior the tool emulates.
        replaced_counts = [0] * len(s_cmds)
        for ln in line_numbers:
            mod = tex_lines[ln - 1]
            for idx, cmd in enumerate(s_cmds):
                mod, replaced = apply_s_cmd(mod, cmd)
                replaced_counts[idx] += replaced
            if scratch:
                out_scratch.append("% " + mod)
            else:
                out_main.append(mod)
        for idx, replaced in enumerate(replaced_counts):
            if replaced == 0:
                raise ValueError(
                    f"Pattern {s_cmds[idx]!r} not found in lines {line_numbers}"
                )

    if out_scratch:
        out_main.append("% --- SCRATCH ---")
        out_main.extend(out_scratch)

    with args.tex_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(out_main) + "\n")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
