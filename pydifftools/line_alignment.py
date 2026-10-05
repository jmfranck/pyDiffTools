"""Align changed words, restore reference whitespace, then check lines."""

from pathlib import Path
import itertools
import re
import subprocess
import tempfile


def minimal_opcodes(before, after):
    """Use Git's minimal Myers diff on sequences of lines or words.

    Unlike difflib.SequenceMatcher, this minimizes insertions and deletions.
    Explicit flags keep user diff settings and external drivers out of the
    alignment. Each sequence item is written as one line for Git.
    """
    if before == after:
        return [("equal", 0, len(before), 0, len(after))] if before else []
    if not before or not after:
        return [
            ("insert" if after else "delete", 0, len(before), 0, len(after))
        ]
    with tempfile.TemporaryDirectory(prefix="pydifft-words-") as directory:
        paths = [Path(directory) / name for name in ("before", "after")]
        for path, items in zip(paths, (before, after)):
            path.write_text(
                "".join(item.rstrip("\r\n") + "\n" for item in items),
                encoding="utf-8",
            )
        diff = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--text",
                "--minimal",
                "--diff-algorithm=myers",
                "--no-indent-heuristic",
                "--unified=0",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--inter-hunk-context=0",
                "--",
                *map(str, paths),
            ],
            capture_output=True,
            text=True,
        )
    if diff.returncode not in (0, 1):
        raise RuntimeError(f"Git word alignment failed: {diff.stderr.strip()}")
    a = b = 0
    result = []
    for match in re.finditer(
        r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
        diff.stdout,
        re.MULTILINE,
    ):
        count_a = int(match[2]) if match[2] is not None else 1
        count_b = int(match[4]) if match[4] is not None else 1
        start_a = int(match[1]) - bool(count_a)
        start_b = int(match[3]) - bool(count_b)
        if a < start_a:
            result.append(("equal", a, start_a, b, start_b))
        end_a, end_b = start_a + count_a, start_b + count_b
        operation = (
            "replace"
            if count_a and count_b
            else ("delete" if count_a else "insert")
        )
        result.append((operation, start_a, end_a, start_b, end_b))
        a, b = end_a, end_b
    if a < len(before) or b < len(after):
        result.append(("equal", a, len(before), b, len(after)))
    return result


def align_line_breaks(
    reference,
    current,
    filetype="markdown",
    width=None,
    punctuation_slop=20,
    preserve_reference_lines=False,
):
    """Return changed hunks with original, linted and proposed layouts.

    Align words with minimal diff, reuse whitespace after matching words,
    then preserve complete reference lines and enforce line linting. CPB
    reviews multiple adjustments; wmatch applies the proposed layout.
    Width can be a number or a function choosing a limit after restoration.
    """
    from .wrap_sentences import (
        WORD,
        classify_lines,
        check_prose,
        apply_markdown_issue_fix,
    )

    prefix_pattern = re.compile(
        r"^(?P<quote>(?:[ \t]*>[ \t]?)*)(?P<indent>[ \t]*)"
        r"(?:(?P<marker>[-+*]|[0-9]+[.)])(?P<space>[ \t]+))?"
    )

    def mask_comments(text):
        return re.sub(
            r"<!--.*?(?:-->|\Z)",
            lambda match: "".join(
                "\n" if c == "\n" else " " for c in match[0]
            ),
            text,
            flags=re.DOTALL,
        )

    def tokenize(text, prose=None, masked=None):
        # {{{ words plus editable whitespace, retaining original offsets
        if masked is None:
            masked = mask_comments(text)
        rows = masked.splitlines(keepends=True)
        if prose is None:
            prose = [
                flag and bool(line.strip())
                for flag, line in classify_lines(
                    masked, filetype, strict=False
                )
            ]
        prefixes = [prefix_pattern.match(line) for line in rows]
        continuation = [
            p["quote"]
            + p["indent"]
            + (
                " " * (len(p["marker"]) + len(p["space"]))
                if p["marker"]
                else ""
            )
            for p in prefixes
        ]
        tokens = []
        position = 0
        for row, line in enumerate(rows):
            tokens.extend(
                (row, position + m.start(), position + m.end())
                for m in WORD.finditer(line, prefixes[row].end())
            )
            position += len(line)
        gaps = {}
        for number, (left, right) in enumerate(zip(tokens, tokens[1:])):
            row, _, end = left
            next_row, start, _ = right
            raw = text[end:start]
            if not (prose[row] and prose[next_row]):
                continue
            if row == next_row:
                if raw.strip(" \t"):
                    continue
            elif (
                next_row != row + 1
                or prefixes[next_row]["marker"]
                or prefixes[next_row].group(0) != continuation[row]
                or raw.strip(" \t\r\n")
                != prefixes[next_row]["quote"].strip(" \t")
            ):
                continue
            gaps[number] = raw
        return masked, tokens, gaps, continuation
        # }}}

    def lint(text, prose):
        if width is None:
            return text, prose
        # Each pass fixes a source line, never realigns its words.
        for _ in range(max(1, len(text.split()))):
            issues = {}
            offset = 1
            flags = [
                allowed
                and not (preserve_reference_lines and line in reference_lines)
                for allowed, line in zip(prose, text.splitlines(keepends=True))
            ]
            for allowed, group in itertools.groupby(
                zip(flags, text.splitlines(keepends=True)),
                key=lambda item: item[0],
            ):
                span = "".join(line for _, line in group)
                if allowed:
                    for line, message in check_prose(
                        mask_comments(span),
                        width,
                        punctuation_slop,
                        offset,
                    ):
                        issues.setdefault(line, message)
                offset += span.count("\n")
            if not issues:
                break
            for line in sorted(issues, reverse=True):
                text = apply_markdown_issue_fix(text, line, issues[line])[0]
                prose = prose[:line] + [True] + prose[line:]
        return text, prose

    reference_lines = reference.splitlines(keepends=True)
    lines = current.splitlines(keepends=True)
    reference_masked = mask_comments(reference)
    current_masked = mask_comments(current)
    reference_prose = [
        flag and bool(line.strip())
        for flag, line in classify_lines(
            reference_masked, filetype, strict=False
        )
    ]
    current_prose = [
        flag and bool(line.strip())
        for flag, line in classify_lines(
            current_masked, filetype, strict=False
        )
    ]
    reference_masked_lines = reference_masked.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    results = []
    requested_width = width
    hunks = [
        item
        for item in minimal_opcodes(reference_lines, lines)
        if item[0] != "equal" and item[3] != item[4]
    ]
    # {{{ batch word diffs, prefixing each word to keep its hunk isolated
    pairs = []
    old_words, new_words, old_locations, new_locations = [], [], [], []
    for hunk, (_, i1, i2, j1, j2) in enumerate(hunks):
        old = tokenize(
            "".join(reference_lines[i1:i2]),
            reference_prose[i1:i2],
            "".join(reference_masked_lines[i1:i2]),
        )
        new = tokenize(
            current[starts[j1] : starts[j2]],
            current_prose[j1:j2],
            current_masked[starts[j1] : starts[j2]],
        )
        pairs.append((old, new))
        for items, words, locations in (
            (old, old_words, old_locations),
            (new, new_words, new_locations),
        ):
            masked, tokens, _, _ = items
            words.extend(f"{hunk}:{masked[a:b]}" for _, a, b in tokens)
            locations.extend((hunk, number) for number in range(len(tokens)))
    matches = [{} for _ in hunks]
    for operation, a, b, c, d in minimal_opcodes(old_words, new_words):
        if operation == "equal":
            for old_index, new_index in zip(range(a, b), range(c, d)):
                _, old_number = old_locations[old_index]
                hunk, number = new_locations[new_index]
                matches[hunk][number] = old_number
    # }}}
    for hunk, (_, i1, i2, j1, j2) in enumerate(hunks):
        start, stop = starts[j1], starts[j2]
        before = current[start:stop]
        width = None if callable(requested_width) else requested_width
        head = "".join(reference_lines[i1:i2])
        (_, old_tokens, old_gaps, _), (_, tokens, gaps, continuation) = pairs[
            hunk
        ]
        whitespace = dict(gaps)
        ending = "\r\n" if "\r\n" in before else "\n"

        def render(spaces):
            output = []
            position = 0
            for number, space in spaces.items():
                end, following = tokens[number][2], tokens[number + 1][1]
                output.extend((before[position:end], space))
                position = following
            output.append(before[position:])
            prose = current_prose[j1:j2]
            for number, space in reversed(list(spaces.items())):
                row = tokens[number][0]
                old_breaks = gaps[number].count("\n")
                new_breaks = space.count("\n")
                prose[row + 1 : row + 1 + old_breaks] = [True] * new_breaks
            return "".join(output), prose

        spans = []
        if gaps:
            # {{{ minimal word alignment restores reference whitespace first
            old_rows = {}
            for number, (row, _, _) in enumerate(old_tokens):
                old_rows.setdefault(row, [number, number])[1] = number
            for number, old_number in matches[hunk].items():
                if number in gaps and old_number in old_gaps:
                    raw = old_gaps[old_number]
                    whitespace[number] = (
                        ending + continuation[tokens[number][0]]
                        if "\n" in raw
                        else raw
                    )
            reverse = {old: new for new, old in matches[hunk].items()}
            for row, (first, last) in old_rows.items():
                if (
                    all(number in reverse for number in range(first, last + 1))
                    and reverse[last] - reverse[first] == last - first
                ):
                    spans.append(
                        (
                            reverse[first],
                            reverse[last],
                            reference_lines[i1 + row].rstrip(),
                        )
                    )
            # }}}
            # {{{ additional breaks preserve a line without tiny new fragments
            inherited = {line.rstrip() for line in reference_lines}
            for first, last, old_line in spans:
                needed = range(
                    max(0, first - 1), min(len(tokens) - 1, last + 1)
                )
                if any(number not in gaps for number in needed):
                    continue
                if width is not None and len(old_line) > width:
                    continue
                proposed = dict(whitespace)
                for number in needed:
                    if number in (first - 1, last):
                        proposed[number] = (
                            ending + continuation[tokens[number][0]]
                        )
                    elif "\n" in proposed[number]:
                        proposed[number] = " "
                original_rows = set(render(whitespace)[0].splitlines())
                proposed_rows = render(proposed)[0].splitlines()
                if old_line not in {line.rstrip() for line in proposed_rows}:
                    continue
                if any(
                    line not in original_rows
                    and line.rstrip() not in inherited
                    and 0 < len("".join(line.split())) < 10
                    for line in proposed_rows
                ):
                    continue
                whitespace = proposed
            # }}}
        restored, restored_prose = render(whitespace)
        if callable(requested_width):
            joined = any(
                "\n" in raw and "\n" not in whitespace[number]
                for number, raw in gaps.items()
            )
            width = requested_width(i1, restored, joined)
        aligned, aligned_prose = lint(restored, restored_prose)
        linted, lint_prose = lint(before, current_prose[j1:j2])
        # {{{ count adjustments between retained boundaries for CPB review
        _, lint_tokens, lint_gaps, _ = tokenize(linted, lint_prose)
        _, aligned_tokens, aligned_gaps, _ = tokenize(aligned, aligned_prose)
        moves = inserted = removed = 0
        previous = None
        if len(lint_tokens) == len(aligned_tokens):
            for number, raw in lint_gaps.items():
                changed = aligned_gaps.get(number, raw)
                old, new = "\n" in raw, "\n" in changed
                if (old and new) or (
                    previous is not None
                    and "\n"
                    in linted[
                        lint_tokens[previous + 1][1] : lint_tokens[number][2]
                    ]
                ):
                    moves += max(inserted, removed)
                    inserted = removed = 0
                inserted += new and not old
                removed += old and not new
                previous = number
            moves += max(inserted, removed)
        if not moves and aligned != linted:
            moves = 1
        # }}}
        results.append(
            {
                "line": j1 + 1,
                "reference_line": i1,
                "start": start,
                "stop": stop,
                "head": head,
                "before": before,
                "linted": linted,
                "aligned": aligned,
                "moves": moves,
            }
        )
    return results
