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


# also used by: match_spaces.run, wrap_sentences.autofix_markdown_file,
# and tests/test_line_alignment.py.
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
    and wmatch apply the aligned layout automatically.
    Width can be a number or a function choosing a limit after restoration.
    """
    from .wrap_sentences import (
        WORD,
        classify_lines,
        markdown_blocks,
        check_prose,
        apply_markdown_issue_fix,
        _html_comment_spans,
        _mask_html_comments,
    )

    prefix_pattern = re.compile(
        r"^(?P<quote>(?:[ \t]*>[ \t]?)*)(?P<indent>[ \t]*)"
        r"(?:(?P<marker>[-+*]|[0-9]+[.)])(?P<space>[ \t]+))?"
    )

    def tokenize(text, prose, comments, base=0):
        # {{{ words plus editable whitespace, retaining original offsets
        rows = text.splitlines(keepends=True)
        delimiters = []
        for begin, end in comments:
            begin, end = begin - base, end - base
            if 0 <= begin < len(text) and text[begin:begin + 4] == "<!--":
                delimiters.append((begin, begin + 4))
            if 0 <= end - 3 < len(text) and text[end - 3:end] == "-->":
                delimiters.append((end - 3, end))
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
            for word in WORD.finditer(line, prefixes[row].end()):
                begin, end = position + word.start(), position + word.end()
                cursor = begin
                for marker_start, marker_end in delimiters:
                    if begin <= marker_start < end:
                        if cursor < marker_start:
                            tokens.append((row, cursor, marker_start))
                        tokens.append((row, marker_start, marker_end))
                        cursor = marker_end
                if cursor < end:
                    tokens.append((row, cursor, end))
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
        return text, tokens, gaps, continuation
        # }}}

    def lint(text, prose, comment_open):
        if width is None:
            return text, prose
        # Each pass fixes a source line, never realigns its words.
        for _ in range(max(1, len(text.split()))):
            issues = {}
            offset = 1
            masked_lines = _mask_html_comments(
                text, initially_open=comment_open
            ).splitlines(keepends=True)
            flags = [
                allowed
                and not (preserve_reference_lines and line in reference_lines)
                for allowed, line in zip(prose, text.splitlines(keepends=True))
            ]
            for allowed, group in itertools.groupby(
                zip(flags, masked_lines),
                key=lambda item: item[0],
            ):
                span = "".join(line for _, line in group)
                if allowed:
                    for line, message in check_prose(
                        span,
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
    reference_masked = _mask_html_comments(reference)
    current_masked = _mask_html_comments(current)
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
    # {{{ identify top-level prose margins without changing container structure
    margins = []
    for masked in (reference_masked, current_masked):
        flags = []
        if filetype == "markdown":
            for block in markdown_blocks(masked):
                flags.extend(
                    [block.kind == "prose"] * len(block.text.splitlines())
                )
        else:
            flags = [False] * len(masked.splitlines())
        margins.append(flags)
    reference_margins, current_margins = margins
    # }}}
    # {{{ align hidden text too, while keeping it excluded from prose lint
    reference_comments = _html_comment_spans(reference)
    current_comments = _html_comment_spans(current)
    reference_alignment = reference_prose[:]
    current_alignment = current_prose[:]
    for text, flags, comments in (
        (reference, reference_alignment, reference_comments),
        (current, current_alignment, current_comments),
    ):
        for begin, end in comments:
            first = text.count("\n", 0, begin)
            last = text.count("\n", 0, max(begin, end - 1))
            flags[first:last + 1] = [True] * (last - first + 1)
    # }}}
    reference_starts = [0]
    for line in reference_lines:
        reference_starts.append(reference_starts[-1] + len(line))
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
            reference_alignment[i1:i2],
            reference_comments, reference_starts[i1],
        )
        new = tokenize(
            current[starts[j1] : starts[j2]],
            current_alignment[j1:j2],
            current_comments, starts[j1],
        )
        pairs.append((old, new))
        for items, words, locations, base, comments in (
            (old, old_words, old_locations, reference_starts[i1],
             reference_comments),
            (new, new_words, new_locations, starts[j1], current_comments),
        ):
            source, tokens, _, _ = items
            for _, a, b in tokens:
                hidden = any(
                    begin <= base + a < end for begin, end in comments
                )
                words.append(f"{hunk}:{hidden}:{source[a:b]}")
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
        comment_open = any(
            begin < start < end for begin, end in current_comments
        )
        width = None if callable(requested_width) else requested_width
        head = "".join(reference_lines[i1:i2])
        (_, old_tokens, old_gaps, _), (_, tokens, gaps, continuation) = pairs[
            hunk
        ]
        whitespace = dict(gaps)
        ending = "\r\n" if "\r\n" in before else "\n"

        # {{{ restore presentation indentation at matching line starts
        old_first = {}
        for number, (row, _, _) in enumerate(old_tokens):
            old_first.setdefault(row, number)
        leading = []
        seen = set()
        for number, (row, _, _) in enumerate(tokens):
            if row in seen:
                continue
            seen.add(row)
            old_number = matches[hunk].get(number)
            if old_number is None:
                continue
            old_row = old_tokens[old_number][0]
            if old_first[old_row] != old_number:
                continue
            line_start = starts[j1 + row]
            old_start = reference_starts[i1 + old_row]
            prefix = re.match(r"[ \t]*", lines[j1 + row])[0]
            old_prefix = re.match(
                r"[ \t]*", reference_lines[i1 + old_row]
            )[0]
            hidden = all(
                any(begin <= offset < end for begin, end in comments)
                for offset, comments in (
                    (line_start, current_comments),
                    (old_start, reference_comments),
                )
            )
            plain = (
                current_prose[j1 + row] and reference_prose[i1 + old_row]
                and current_margins[j1 + row]
                and reference_margins[i1 + old_row]
                and "\t" not in prefix + old_prefix
                and max(len(prefix), len(old_prefix)) < 4
            )
            if prefix != old_prefix and (hidden or plain):
                leading.append((
                    line_start - start,
                    line_start - start + len(prefix),
                    old_prefix,
                ))
        # }}}

        def render(spaces):
            edits = [
                (tokens[number][2], tokens[number + 1][1], space)
                for number, space in spaces.items()
            ]
            for begin, end, prefix in leading:
                for index, (left, right, space) in enumerate(edits):
                    if left < begin and end == right:
                        if "\n" in space:
                            edits[index] = (
                                left, right, space[:space.rfind("\n") + 1]
                                + prefix,
                            )
                        break
                else:
                    edits.append((begin, end, prefix))
            output = []
            position = 0
            for begin, end, space in sorted(edits):
                output.extend((before[position:begin], space))
                position = end
            output.append(before[position:])
            prose = current_prose[j1:j2]
            for number, space in reversed(list(spaces.items())):
                row = tokens[number][0]
                old_breaks = gaps[number].count("\n")
                new_breaks = space.count("\n")
                allowed = any(prose[row:row + old_breaks + 1])
                prose[row:row + old_breaks + 1] = [allowed] * (new_breaks + 1)
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
                    inside_comment = any(
                        begin <= start + tokens[number][1]
                        and start + tokens[number + 1][1] < end
                        for begin, end in current_comments
                    )
                    if inside_comment:
                        whitespace[number] = re.sub(r"\r?\n", ending, raw)
                    else:
                        whitespace[number] = (
                            ending + continuation[tokens[number][0]]
                            if "\n" in raw else raw
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
                original_rows = set(render(whitespace)[0].splitlines())
                inside_comment = any(
                    begin <= start + tokens[first][1]
                    and start + tokens[last][1] < end
                    for begin, end in current_comments
                )
                if inside_comment and old_line in {
                    line.rstrip() for line in original_rows
                }:
                    continue
                proposed = dict(whitespace)
                for number in needed:
                    if number in (first - 1, last):
                        proposed[number] = (
                            ending + continuation[tokens[number][0]]
                        )
                    elif "\n" in proposed[number]:
                        proposed[number] = " "
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
        aligned, aligned_prose = lint(restored, restored_prose, comment_open)
        linted, lint_prose = lint(before, current_prose[j1:j2], comment_open)
        # {{{ count adjustments between retained boundaries for CPB review
        _, lint_tokens, lint_gaps, _ = tokenize(
            linted, lint_prose, _html_comment_spans(linted, comment_open),
        )
        _, aligned_tokens, aligned_gaps, _ = tokenize(
            aligned, aligned_prose, _html_comment_spans(aligned, comment_open),
        )
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
