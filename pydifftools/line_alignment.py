"""Align changed words, restore reference whitespace, then check lines."""

from pathlib import Path
from bisect import bisect_left, bisect_right
import itertools
import re
import subprocess
import tempfile

from .wrapping_options import DEFAULT_DESIRED_WIDTH


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
    desired_width=DEFAULT_DESIRED_WIDTH,
):
    """Return changed hunks with original, linted and proposed layouts.

    Align words with minimal diff, reuse equivalent source whitespace,
    then preserve complete reference lines and enforce line linting. CPB
    and wmatch apply the aligned layout automatically.
    Width can be a number or a function choosing a limit after restoration.
    Restore whitespace before re-diffing and checking changed source lines.
    """
    from .wrap_sentences import (
        WORD,
        classify_lines,
        markdown_blocks,
        check_prose,
        apply_markdown_issue_fix,
        structural_rows,
        _mask_html_comments,
    )

    prefix_pattern = re.compile(
        r"^(?P<quote>(?:[ \t]*>[ \t]?)*)(?P<indent>[ \t]*)"
        r"(?:(?P<marker>[-+*]|[0-9]+[.)])(?P<space>[ \t]+))?"
    )

    def region_at(regions, position):
        index = bisect_left(regions, (position + 1,)) - 1
        if index >= 0 and position < regions[index][1]:
            return regions[index]
        return None

    def source_layout(text):
        # {{{ classify structural whitespace independently of prose lint
        comments, equations, structural, allowed = structural_rows(
            text, filetype,
        )
        regions = sorted(comments + equations)
        rows = text.splitlines(keepends=True)
        margins = []
        if filetype == "markdown":
            for block in markdown_blocks(structural):
                margins.extend(
                    [block.kind == "prose"] * len(block.text.splitlines())
                )
        else:
            margins = [False] * len(rows)
        position = 0
        prefixes = []
        for row, line in enumerate(rows):
            indent = re.match(r"[ \t]*", line)[0]
            inside = region_at(regions, position) is not None
            prefixes.append(prefix_pattern.match(indent if inside else line))
            margins[row] = allowed[row] and (
                inside or (
                    margins[row] and "\t" not in indent and len(indent) < 4
                    and not (
                        row and not rows[row - 1].strip() and len(indent) >= 2
                    )
                )
            )
            position += len(line)
        return comments, equations, allowed, margins, prefixes
        # }}}

    def tokenize(text, layout, base=0):
        # {{{ words plus editable whitespace, retaining original offsets
        comments, equations, allowed, margins, prefixes = layout
        regions = sorted(comments + equations)
        rows = text.splitlines(keepends=True)
        cuts = set()
        for begin, end in comments:
            begin, end = begin - base, end - base
            if 0 <= begin < len(text) and text[begin:begin + 4] == "<!--":
                cuts.update((begin, begin + 4))
            if 0 <= end - 3 < len(text) and text[end - 3:end] == "-->":
                cuts.update((end - 3, end))
        for begin, end in equations:
            cuts.update((begin - base, end - base))
        continuation = [
            p["quote"] + p["indent"]
            + (" " * (len(p["marker"]) + len(p["space"]))
               if p["marker"] else "")
            for p in prefixes
        ]
        span_word = re.compile(
            r"\$\$|\$|\\[A-Za-z]+|\\[^\s]|[A-Za-z]+|[0-9]+(?:\.[0-9]+)?|[^\s]"
        )
        tokens = []
        position = 0
        for row, line in enumerate(rows):
            begin = position + prefixes[row].end()
            end = position + len(line)
            boundaries = [begin, *sorted(c for c in cuts if begin < c < end),
                          end]
            for left, right in zip(boundaries, boundaries[1:]):
                in_math = region_at(equations, base + left) is not None
                hidden = region_at(comments, base + left) is not None
                # Hidden source has no rendered word boundaries. Separate
                # punctuation there too, so layout changes do not turn
                # "$$R_c" into unmatched "$$" and "R_c" tokens.
                pattern = span_word if in_math or hidden else WORD
                tokens.extend(
                    (row, match.start(), match.end())
                    for match in pattern.finditer(text, left, right)
                )
            position += len(line)
        gaps = {}
        for number, (left, right) in enumerate(zip(tokens, tokens[1:])):
            row, _, end = left
            next_row, start, _ = right
            raw = text[end:start]
            if not (allowed[row] and allowed[next_row]):
                continue
            region = region_at(regions, base + left[1])
            free = region is not None and base + start < region[1]
            if row == next_row:
                if raw.strip(" \t"):
                    continue
            elif not (free and not raw.strip(" \t\r\n")) and (
                next_row != row + 1
                or prefixes[next_row]["marker"]
                or (prefixes[next_row].group(0) != continuation[row]
                    and not (margins[row] and margins[next_row]))
                or raw.strip(" \t\r\n")
                != prefixes[next_row]["quote"].strip(" \t")
            ):
                continue
            gaps[number] = raw
        return text, tokens, gaps, continuation
        # }}}

    def lint(text, eligible):
        if width is None:
            return text
        # Reclassify the enclosing blocks after layout changes.
        for _ in range(max(1, len(text.split()))):
            full_source = (
                current[context_start:start] + text
                + current[stop:context_stop]
            )
            masked = _mask_html_comments(full_source)
            classified = classify_lines(masked, filetype, strict=False)
            rows = text.splitlines(keepends=True)
            # A row that the fresh line diff found identical to the
            # reference keeps its layout (it adds no diff), unless it is
            # wider than the hard width and reference lines aren't
            # preserved outright (wmatch).
            flags = [
                allowed and (row in eligible or (
                    not preserve_reference_lines
                    and len(rows[row].rstrip("\r\n")) > width
                ))
                for row, (allowed, _) in enumerate(
                    classified[context_row:context_row + len(rows)]
                )
            ]
            issues = {}
            offset = 1
            masked_lines = masked[
                local_start:local_start + len(text)
            ].splitlines(keepends=True)
            for allowed, group in itertools.groupby(
                zip(flags, masked_lines), key=lambda item: item[0],
            ):
                span = "".join(line for _, line in group)
                if allowed:
                    for line, message in check_prose(
                        span, width, punctuation_slop, offset,
                        overflow_words=0,
                    ):
                        issues.setdefault(line, message)
                offset += span.count("\n")
            if not issues:
                break
            for line in sorted(issues, reverse=True):
                updated = apply_markdown_issue_fix(
                    full_source, context_row + line, issues[line],
                )[0]
                added = updated.count("\n") - full_source.count("\n")
                eligible = {
                    row if row < line else row + added for row in eligible
                } | set(range(line - 1, line + added))
                full_source = updated
            text = full_source[
                local_start:len(full_source) - len(current[stop:context_stop])
            ]
        return text

    reference_lines = reference.splitlines(keepends=True)
    lines = current.splitlines(keepends=True)
    reference_layout = source_layout(reference)
    current_layout = source_layout(current)
    current_comments, current_equations = current_layout[:2]
    reference_starts = [0]
    for line in reference_lines:
        reference_starts.append(reference_starts[-1] + len(line))
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    # {{{ bound hunk context at blank lines outside protected source spans
    regions = sorted(current_comments + current_equations)
    region_starts = [begin for begin, _ in regions]
    boundaries = [0]
    for row, (allowed, line) in enumerate(classify_lines(
        _mask_html_comments(current), filetype, strict=False,
    )):
        region = bisect_left(region_starts, starts[row + 1]) - 1
        inside = region >= 0 and regions[region][1] > starts[row]
        if allowed and not line.strip() and not inside:
            boundaries.append(row + 1)
    if boundaries[-1] != len(lines):
        boundaries.append(len(lines))
    # }}}
    results = []
    restored_hunks = []
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
            (*reference_layout[:2], *(
                flags[i1:i2] for flags in reference_layout[2:]
            )), reference_starts[i1],
        )
        new = tokenize(
            current[starts[j1] : starts[j2]],
            (*current_layout[:2], *(
                flags[j1:j2] for flags in current_layout[2:]
            )), starts[j1],
        )
        pairs.append((old, new))
        for items, words, locations, base, layout in (
            (old, old_words, old_locations, reference_starts[i1],
             reference_layout),
            (new, new_words, new_locations, starts[j1], current_layout),
        ):
            source, tokens, _, _ = items
            for _, a, b in tokens:
                hidden = region_at(layout[0], base + a) is not None
                math = region_at(layout[1], base + a) is not None
                words.append(f"{hunk}:{hidden}:{math}:{source[a:b]}")
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
        context_first = boundaries[bisect_right(boundaries, j1) - 1]
        context_last = boundaries[bisect_left(boundaries, j2)]
        context_start = starts[context_first]
        context_stop = starts[context_last]
        before = current[start:stop]
        head = "".join(reference_lines[i1:i2])
        (_, old_tokens, old_gaps, _), (_, tokens, gaps, continuation) = pairs[
            hunk
        ]
        whitespace = dict(gaps)
        ending = "\r\n" if "\r\n" in before else "\n"

        def equivalent_gap(number, replacement):
            # {{{ keep rendered separators and explicit Markdown hard breaks
            raw = gaps[number]
            left = start + tokens[number][1]
            right = start + tokens[number + 1][1]
            region = region_at(current_comments, left)
            if region is not None and right < region[1]:
                return True
            region = region_at(current_equations, left)
            if region is not None and right < region[1]:
                # Display delimiters can sit on their own source lines.
                # All other math gaps obey the same rule as prose; no
                # knowledge of TeX commands or text macros is needed.
                if current[region[0]:region[0] + 2] == "$$" and (
                    tokens[number][1] + start == region[0]
                    or tokens[number + 1][2] + start == region[1]
                ):
                    return True
                return bool(raw) == bool(replacement)
            # Collapsing a whitespace run retains one separator. It cannot
            # create a separator from an empty gap or remove the last one.
            # Line margins are handled separately, with structural margins
            # excluded. Two spaces before a newline are a Markdown hard
            # break, and a newline after a backslash is explicit as well.
            if any(re.search(r" {2,}\r?\n", gap)
                   for gap in (raw, replacement)) or (
                before[tokens[number][2] - 1:tokens[number][2]] == "\\"
                and ("\n" in raw or "\n" in replacement)
            ):
                return raw == replacement
            return bool(raw) == bool(replacement)
            # }}}

        # {{{ restore presentation indentation at matching line starts
        old_first = {}
        for number, (row, _, _) in enumerate(old_tokens):
            old_first.setdefault(row, number)
        matched_old = set(matches[hunk].values())
        leading = []
        seen = set()
        for number, (row, _, _) in enumerate(tokens):
            if row in seen:
                continue
            seen.add(row)
            old_number = matches[hunk].get(number)
            if old_number is None and number + 1 < len(tokens):
                following = matches[hunk].get(number + 1)
                if (
                    following is not None and following > 0
                    and tokens[number + 1][0] == row
                    and following - 1 not in matched_old
                    and old_first[old_tokens[following][0]] == following - 1
                ):
                    old_number = following - 1
            if old_number is None:
                continue
            old_row = old_tokens[old_number][0]
            if old_first[old_row] != old_number:
                continue
            line_start = starts[j1 + row]
            prefix = re.match(r"[ \t]*", lines[j1 + row])[0]
            old_prefix = re.match(
                r"[ \t]*", reference_lines[i1 + old_row]
            )[0]
            if (
                prefix != old_prefix
                and current_layout[3][j1 + row]
                and reference_layout[3][i1 + old_row]
            ):
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
            return "".join(output)

        spans = []
        if gaps:
            # {{{ minimal word alignment restores reference whitespace first
            reverse = {old: new for new, old in matches[hunk].items()}
            old_rows = {}
            for number, (row, _, _) in enumerate(old_tokens):
                old_rows.setdefault(row, [number, number])[1] = number
            for first, last in old_rows.values():
                if (
                    all(number in reverse for number in range(first, last + 1))
                    and reverse[last] - reverse[first] == last - first
                ):
                    spans.append((
                        reverse[first], reverse[last],
                    ))
            for number in gaps:
                old_number = matches[hunk].get(number)
                if old_number is None and number + 1 in matches[hunk]:
                    candidate = matches[hunk][number + 1] - 1
                    if candidate not in reverse:
                        old_number = candidate
                if old_number in old_gaps:
                    raw = old_gaps[old_number]
                    if not equivalent_gap(number, raw):
                        continue
                    region = region_at(regions, start + tokens[number][1])
                    inside_region = (
                        region is not None
                        and start + tokens[number + 1][1] < region[1]
                    )
                    if inside_region or (
                        current_layout[3][j1 + tokens[number][0]]
                        and current_layout[3][j1 + tokens[number + 1][0]]
                    ):
                        whitespace[number] = re.sub(r"\r?\n", ending, raw)
                    else:
                        whitespace[number] = (
                            ending + continuation[tokens[number][0]]
                            if "\n" in raw else raw
                        )
            # }}}
            # {{{ restore complete reference lines before applying guards
            for first, last in spans:
                needed = range(
                    max(0, first - 1), min(len(tokens) - 1, last + 1)
                )
                if any(number not in gaps for number in needed):
                    continue
                proposed = {}
                for number in needed:
                    if number in (first - 1, last):
                        proposed[number] = (
                            whitespace[number] if "\n" in whitespace[number]
                            else ending + continuation[tokens[number][0]]
                        )
                    else:
                        proposed[number] = (
                            " " if "\n" in whitespace[number]
                            else whitespace[number]
                        )
                if any(
                    not equivalent_gap(number, proposed[number])
                    for number in needed
                ):
                    continue
                # Check only this line's body, rather than copying and
                # rendering the entire hunk for every inherited line.
                if "".join(
                    before[tokens[number][1]:tokens[number][2]]
                    + (proposed[number] if number < last else "")
                    for number in range(first, last + 1)
                ) != head[
                    old_tokens[matches[hunk][first]][1]:
                    old_tokens[matches[hunk][last]][2]
                ]:
                    continue
                whitespace.update(proposed)
            # }}}
        restored_hunks.append((
            render(whitespace), i1, i2, j1, j2,
            context_first, context_start, context_stop, gaps,
        ))
    # {{{ re-diff the complete restored source in one Git diff
    new_rows, restored_starts = [], []
    position = 0
    for restored, _, _, j1, j2, *_ in restored_hunks:
        new_rows.extend(lines[position:j1])
        restored_starts.append(len(new_rows))
        new_rows.extend(restored.splitlines(keepends=True))
        position = j2
    new_rows.extend(lines[position:])
    changed_rows = set()
    for operation, _, _, a, b in minimal_opcodes(reference_lines, new_rows):
        if operation != "equal":
            changed_rows.update(range(a, b))
    # }}}
    for hunk, (
        restored, i1, i2, j1, j2,
        context_first, context_start, context_stop, original_gaps,
    ) in enumerate(restored_hunks):
        start, stop = starts[j1], starts[j2]
        local_start = start - context_start
        context_row = j1 - context_first
        before = current[start:stop]
        head = "".join(reference_lines[i1:i2])
        width = None if callable(requested_width) else requested_width
        eligible = {
            row for row in range(len(restored.splitlines()))
            if restored_starts[hunk] + row in changed_rows
        }
        # {{{ apply guards only after restoration and the fresh line diff
        full_source = (
            current[context_start:start] + restored
            + current[stop:context_stop]
        )
        layout = source_layout(full_source)
        _, restored_tokens, restored_gaps, _ = tokenize(
            restored, (*layout[:2], *(
                flags[context_row:context_row + len(restored.splitlines())]
                for flags in layout[2:]
            )), local_start,
        )
        if callable(requested_width):
            width = requested_width(i1, restored, any(
                "\n" in raw and "\n" not in restored_gaps.get(number, raw)
                for number, raw in original_gaps.items()
            ))
        rows = restored.splitlines(keepends=True)
        edits = {}
        row_starts = [0]
        for line in rows:
            row_starts.append(row_starts[-1] + len(line))
        original_rows = {line.strip() for line in before.splitlines()}
        word_ends = [match.end() for match in re.finditer(r"\S+", restored)]
        for number, raw in restored_gaps.items():
            if number not in original_gaps:
                continue
            row, _, end = restored_tokens[number]
            next_row, begin, _ = restored_tokens[number + 1]
            if preserve_reference_lines and (
                row not in eligible or next_row not in eligible
            ):
                continue
            # Hidden source and display math retain their reference layout.
            if any(
                region_at(regions, local_start + end - 1) is not None
                and region_at(regions, local_start + begin) is not None
                for regions in layout[:2]
            ):
                continue
            if "\n" in original_gaps[number] and "\n" not in raw:
                # Restoration joined a break the user had.  Past the hard
                # width the row must be split anyway, so the user's break
                # is put back.  Above desired_width it is put back only if
                # it costs no anchor words: a break between two words that
                # are neighbours on one reference line would leave both
                # of them in the diff.
                # (So a row identical to the reference, whose breaks all
                # fall between anchor words, keeps the reference layout.)
                old = matches[hunk].get(number)
                length = len(rows[row].rstrip("\r\n"))
                if (
                    width is not None and length > width
                    or length > desired_width and not (
                        old is not None
                        and matches[hunk].get(number + 1) == old + 1
                        and "\n" not in pairs[hunk][0][2].get(old, "\n")
                    )
                ) and all(
                    bisect_right(word_ends, right)
                    - bisect_right(word_ends, left) > 3
                    or restored[left:right].strip() in original_rows
                    for left, right in (
                        (row_starts[row], end),
                        (begin, row_starts[row + 1]),
                    )
                ):
                    edits[number] = original_gaps[number]
            elif "\n" in raw and (
                preserve_reference_lines or "\n" not in original_gaps[number]
            ) and not (
                re.search(r" {2,}\r?\n", raw)
                or restored[end - 1:end] == "\\"
            ):
                if any(
                    r in eligible and len(rows[r].split()) <= 3
                    for r in (row, next_row)
                ) and (
                    "\n" not in original_gaps[number]
                    or len(rows[row].rstrip("\r\n"))
                    + len(rows[next_row].strip()) + 1 <= desired_width
                ):
                    edits[number] = (
                        " " if "\n" in original_gaps[number]
                        else original_gaps[number]
                    )
        output = []
        position = 0
        guarded_eligible = set()
        guarded_row = 0
        # Carry fresh-diff eligibility through the whitespace edits; no new
        # Git subprocess is needed when the subsequent lint inserts lines.
        row_deltas = [0] * len(rows)
        for number, replacement in edits.items():
            row_deltas[restored_tokens[number][0]] += (
                replacement.count("\n") - restored_gaps[number].count("\n")
            )
        for row, line in enumerate(rows):
            if row in eligible:
                guarded_eligible.update(range(
                    guarded_row, guarded_row + max(1, 1 + row_deltas[row]),
                ))
            guarded_row += line.count("\n") + row_deltas[row]
        for number, replacement in sorted(edits.items()):
            left = restored_tokens[number][2]
            right = restored_tokens[number + 1][1]
            output.extend((restored[position:left], replacement))
            position = right
        output.append(restored[position:])
        aligned = lint("".join(output), guarded_eligible)
        linted = aligned if restored == before else lint(
            before, set(range(len(before.splitlines()))),
        )
        # }}}
        # {{{ count adjustments between retained boundaries for CPB review
        layouts = []
        for text in (linted, aligned):
            layout = source_layout(
                current[context_start:start] + text
                + current[stop:context_stop]
            )
            layouts.append((
                *layout[:2], *(
                    flags[context_row:context_row + len(text.splitlines())]
                    for flags in layout[2:]
                ),
            ))
        _, lint_tokens, lint_gaps, _ = tokenize(
            linted, layouts[0], local_start,
        )
        _, aligned_tokens, aligned_gaps, _ = tokenize(
            aligned, layouts[1], local_start,
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
