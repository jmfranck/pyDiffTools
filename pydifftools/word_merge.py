"""Word-wise three-way merge of Git conflicts, resolved in gvim.

The right-hand pane is a word-level merge of the full base, local and
remote files (Git's index stages 1-3).  Moves are found first, separately
for base→local and base→remote, so that text one side moved and the other
side edited in place can be shown, with both sets of edits, at both ends
of the move -- even where Git reported no conflict.
"""

from bisect import bisect_right
from itertools import product
from pathlib import Path
import re
import subprocess
import tempfile

from .command_registry import register_command
from .line_alignment import align_line_breaks, minimal_opcodes
from .wrap_sentences import structural_rows

# keys of the tokens for line breaks that matter (blank line, other)
BREAKS = ("¶", "↵")


def tokenize(text, filetype="markdown"):
    """Split text into (key, word, gap) tokens.

    Line breaks that matter to the typesetting -- blank lines, and breaks
    next to headers, list items, fences and other lines that
    classify_lines will not rewrap -- become tokens of their own, with key
    "¶" (blank line) or "↵", so a word diff can neither drop nor merge
    them.  Comments and math are masked first, as in
    line_alignment.align_line_breaks, so breaks inside them stay free.
    """
    # {{{ which rows are freely rewrappable prose
    rows = text.splitlines(keepends=True)
    starts = [0]
    for row in rows:
        starts.append(starts[-1] + len(row))
    free = [
        flag and not re.match(
            r"[ \t]*(?:[-+*]|[0-9]+[.)])[ \t]|[ \t]*>", row,
        )
        for flag, row in zip(structural_rows(text, filetype)[3], rows)
    ]
    # }}}
    words = list(re.finditer(r"\S+", text))
    lead = text[: words[0].start()] if words else text
    tokens = []
    for k, match in enumerate(words):
        end = words[k + 1].start() if k + 1 < len(words) else len(text)
        gap = text[match.end(): end]
        if "\n" in gap and k + 1 < len(words):
            before = bisect_right(starts, match.start()) - 1
            after = bisect_right(starts, words[k + 1].start()) - 1
            if after - before > 1 or not (free[before] and free[after]):
                tokens.append((match.group(), match.group(), ""))
                tokens.append(("¶" if after - before > 1 else "↵", gap, ""))
                continue
        tokens.append((match.group(), match.group(), gap))
    return lead, tokens


def joined(pieces):
    """Text of tokens, without the gap after the last one."""
    return "".join(
        word + (gap if k + 1 < len(pieces) else "")
        for k, (_, word, gap) in enumerate(pieces)
    )


# also used by: tests/test_word_merge.py, which checks the gvim panes.
def conflict_views(text):
    """Return the draft (conflicts replaced by base) and its conflict spans.

    The spans are (start, stop) character offsets of each conflict's base
    text within the draft.
    """
    draft = []
    spans = []
    length = 0
    state = None
    for line in text.splitlines(keepends=True):
        if state is None:
            if line.startswith("<<<<<<<"):
                state = "local"
                spans.append([length, length])
            else:
                draft.append(line)
                length += len(line)
        elif state == "local":
            if line.startswith("|||||||"):
                state = "base"
            elif line.startswith("======="):
                raise ValueError(
                    "this conflict has no base (|||||||) section, so a"
                    " word-wise merge is impossible.\n"
                    "Turn on diff3-style conflicts with\n"
                    "    git config --global merge.conflictstyle diff3\n"
                    "and then recreate the markers in this file with\n"
                    "    git checkout --conflict=diff3 -- FILE"
                )
        elif state == "base":
            if line.startswith("======="):
                state = "remote"
                spans[-1][1] = length
            else:
                draft.append(line)
                length += len(line)
        elif line.startswith(">>>>>>>"):
            state = None
    if state is not None:
        raise ValueError("unterminated conflict block")
    return "".join(draft), [tuple(span) for span in spans]


# also used by: tests/test_word_merge.py, which checks merges directly.
def merge_texts(
    base, local, remote, merged=None, filetype="markdown", seed=4,
    min_move=6, anchor=4,
):
    """Merge local and remote edits of base, word by word.

    Moves come first, found separately for base→local and base→remote:
    runs of ``seed``-word sequences that occur once in each text are
    "in place" when they belong to the heaviest chain of runs in order,
    and "moved" otherwise.  Moved runs whose sources and targets are both
    close are chained, and a chain with at least ``min_move`` matching
    words, at least half of its length, is a move.  Each moved span is
    then replaced by a placeholder before the in-place word diff, so the
    moved text cannot confuse that alignment.

    Edits on one side are applied silently.  Edits that clash become
    ``[-base][L+local][R+remote]``, and bracket groups merge unless at
    least ``anchor`` consecutive words between them are unchanged.  When
    the other side edited moved text in place, or either end of a move
    lies in one of Git's conflicts (found from ``merged``, the file with
    conflict markers), its source is shown as ``[L →m00]`` and its
    target as ``[L m00→ text]`` (moves are numbered in hex), where text
    marks both sides' edits, e.g.
    ``[L-John][L+Bob]`` and ``[R-cheese][R+ham]``.
    """
    leads, tokens = zip(*(tokenize(t, filetype)
                          for t in (base, local, remote)))
    tokens = list(tokens)
    tags = {1: "L", 2: "R"}

    def diff_hunks(old, new, side, new_lead, places):
        """Hunks turning old into new, and the (base index, new index,
        token) triples left unchanged.

        places maps indices of old to base indices.  An equal run of
        fewer than ``anchor`` words between two changes that are both
        bigger than it is a chance match, and joins them.
        """
        changes = []
        pairs = []
        for operation, i1, i2, j1, j2 in minimal_opcodes(
            [t[0] for t in old], [t[0] for t in new]
        ):
            if operation == "equal":
                pairs += [(places[i], j, new[j])
                          for i, j in zip(range(i1, i2), range(j1, j2))]
                continue
            if changes:
                run = i1 - changes[-1][1]
                if run < anchor and min(
                    max(changes[-1][1] - changes[-1][0],
                        changes[-1][3] - changes[-1][2]),
                    max(i2 - i1, j2 - j1),
                ) > run and "¶" not in [
                    t[0] for t in old[changes[-1][1]: i1]
                ]:
                    changes[-1][1] = i2
                    changes[-1][3] = j2
                    continue
            changes.append([i1, i2, j1, j2])
        return [
            {
                "side": side, "start": places[i1], "stop": places[i2],
                "tokens": new[j1:j2],
                # the side's token in front, whose whitespace (or, for a
                # line break token, indentation) the hunk keeps
                "before": new[j1 - 1] if j1 else ("", "", new_lead),
            }
            for i1, i2, j1, j2 in changes
        ], pairs

    def attach(result, before):
        """Give the change that follows result the whitespace its side has
        in front of it (before: that side's preceding token), so text
        added at the end of a line stays on that line and a deleted line
        break does not glue words together."""
        if result[-1][0] == before[0]:
            result[-1] = before
        else:
            result[-1] = result[-1][:2] + (
                before[1] + before[2] if before[0] in BREAKS
                else before[2],
            )

    def apply(chosen, start, stop, result=None):
        """Append base[start:stop], with chosen hunks applied, to result."""
        result = [] if result is None else result
        position = start
        for hunk in sorted(chosen, key=lambda h: (h["start"], h["stop"])):
            result += tokens[0][position: hunk["start"]]
            if hunk["start"] and result and hunk["before"] is not None:
                attach(result, hunk["before"])
            result += hunk["tokens"]
            position = hunk["stop"]
        return result + tokens[0][position:stop]

    def one_side(hunks, side):
        return [h for h in hunks if h["side"] == side]

    def render(start, stop, chosen, show_all):
        """Tokens of base[start:stop] merged with the chosen hunks.

        With show_all, every hunk is bracketed (inside moves); otherwise
        only clashing ones are.
        """
        # {{{ clusters of hunks with overlapping base ranges
        clusters = []
        for hunk in sorted(
            chosen, key=lambda h: (h["start"], h["stop"], h["side"])
        ):
            if clusters and (
                hunk["start"] < clusters[-1]["stop"]
                or hunk["start"] == hunk["stop"] == clusters[-1]["start"]
                == clusters[-1]["stop"]
            ):
                clusters[-1]["hunks"].append(hunk)
                clusters[-1]["stop"] = max(clusters[-1]["stop"],
                                           hunk["stop"])
            else:
                clusters.append({"start": hunk["start"],
                                 "stop": hunk["stop"], "hunks": [hunk]})
        # }}}
        # {{{ bracket clashes, then join brackets with too few anchors;
        #     move marks are never joined into other brackets
        groups = []
        for cluster in clusters:
            cluster["barrier"] = any(
                t[0] in ("m→", "→m")
                for h in cluster["hunks"] for t in h["tokens"]
            )
            versions = [
                [t[0] for t in apply(
                    one_side(cluster["hunks"], side),
                    cluster["start"], cluster["stop"],
                )]
                for side in (1, 2)
            ]
            cluster["shown"] = show_all or (
                len({h["side"] for h in cluster["hunks"]}) == 2
                and versions[0] != versions[1]
            )
            back = None
            if cluster["shown"] and not cluster["barrier"]:
                for k in range(len(groups) - 1, -1, -1):
                    if groups[k]["barrier"]:
                        break
                    if groups[k]["shown"]:
                        back = k
                        break
            if back is not None:
                longest = 0
                position = groups[back]["stop"]
                for group in groups[back + 1:] + [cluster]:
                    longest = max(longest, group["start"] - position)
                    position = max(position, group["stop"])
                if longest < anchor:
                    groups[back:] = [{
                        "start": groups[back]["start"],
                        "stop": max(g["stop"] for g in groups[back:]
                                    + [cluster]),
                        "hunks": [h for g in groups[back:] + [cluster]
                                  for h in g["hunks"]],
                        "shown": True, "barrier": False,
                    }]
                    continue
            groups.append(cluster)
        # }}}
        result = []
        position = start
        for index, group in enumerate(groups):
            if not group["shown"]:
                result += tokens[0][position: group["start"]]
                position = group["stop"]
                side = 1 if any(h["side"] == 1 for h in group["hunks"]) \
                    else 2
                result = apply(
                    one_side(group["hunks"], side),
                    group["start"], group["stop"], result,
                )
                continue
            # {{{ [-base][L+local][R+remote], trimmed of shared ends, but
            #     widened until the square brackets inside every part
            #     balance (so dS and the highlighting find the right "]")
            sides = sorted({h["side"] for h in group["hunks"]})
            first, last = group["start"], group["stop"]
            limit = groups[index + 1]["start"] if index + 1 < len(groups) \
                else stop
            caps = [len(tokens[0])] * 2
            while True:
                versions = [tokens[0][first:last]] + [
                    apply(one_side(group["hunks"], side),
                          first, last)
                    for side in sides
                ]
                if len(sides) == 1:
                    labels = [tags[sides[0]] + "-", tags[sides[0]] + "+"]
                elif [t[0] for t in versions[1]] == [t[0] for t in
                                                     versions[2]]:
                    versions = versions[:2]
                    labels = ["-", "+"]
                else:
                    labels = ["-", "L+", "R+"]
                prefix = 0
                while prefix < caps[0] and all(
                    prefix < len(v) for v in versions
                ) and len({v[prefix][0] for v in versions}) == 1:
                    prefix += 1
                suffix = 0
                while suffix < caps[1] and all(
                    prefix + suffix < len(v) for v in versions
                ) and len({v[len(v) - 1 - suffix][0]
                           for v in versions}) == 1:
                    suffix += 1
                need = [False, False]
                for v in versions:
                    depth = lowest = 0
                    for character in joined(v[prefix: len(v) - suffix]):
                        if character == "[":
                            depth += 1
                        elif character == "]":
                            depth -= 1
                            lowest = min(lowest, depth)
                    need[0] |= lowest < 0
                    need[1] |= depth > lowest
                grown = False
                if need[0]:
                    if prefix:
                        caps[0] = prefix - 1
                        grown = True
                    elif first > position:
                        first -= 1
                        caps[0] = 0
                        grown = True
                if need[1]:
                    if suffix:
                        caps[1] = suffix - 1
                        grown = True
                    elif last < limit:
                        last += 1
                        caps[1] = 0
                        grown = True
                if not grown:
                    break
            result += tokens[0][position:first]
            position = last
            # clashing insertions keep the base's whitespace after them,
            # and take their side's in front of them, as apply does
            trailing = None
            if first == last and result and \
                    group["hunks"][0]["before"] is not None:
                trailing = result[-1][2]
                attach(result, group["hunks"][0]["before"])
            cores = [
                (label, v[prefix: len(v) - suffix])
                for label, v in zip(labels, versions)
                if len(v) > prefix + suffix
            ]
            parts = [(label, joined(core), core[-1])
                     for label, core in cores]
            # {{{ when one side only touched up the base text that the
            #     other side rewrote, show the base once, with the light
            #     edits inline, instead of repeating it
            low = first + prefix
            high = last - suffix
            if labels == ["-", "L+", "R+"] and high - low >= 2 * anchor:
                kept = {}
                for side in (1, 2):
                    mine = one_side(group["hunks"], side)
                    if all(low <= h["start"] and h["stop"] <= high
                           for h in mine):
                        kept[side] = 1 - sum(
                            h["stop"] - h["start"] for h in mine
                        ) / (high - low)
                for side, other in ((1, 2), (2, 1)):
                    if kept.get(side, 0) >= 0.5 > kept.get(other, 0):
                        core = dict(cores)[tags[other] + "+"]
                        parts = [
                            (tags[other] + "-", joined(render(
                                low, high,
                                one_side(group["hunks"], side),
                                True,
                            )), tokens[0][high - 1]),
                            (tags[other] + "+", joined(core), core[-1]),
                        ]
            # }}}
            result += versions[0][:prefix]
            text = ""
            for k, (label, body, last) in enumerate(parts):
                text += "[" + label + body + "]"
                # a multi-line part that ended a line puts the next part
                # on a new line
                if k + 1 < len(parts) and "\n" in body \
                        and "\n" in last[1] + last[2]:
                    text += "\n"
            result.append((
                "[", text,
                parts[0][2][2] if trailing is None else trailing,
            ))
            result += versions[0][len(versions[0]) - suffix:]
            # }}}
        return result + tokens[0][position:stop]

    hunks = []
    moves = []
    pairs = {}
    for side in (1, 2):
        old, new = tokens[0], tokens[side]
        # {{{ runs of seed-word sequences that occur once in each text
        counts = {}
        for which, seq in enumerate((old, new)):
            for i in range(len(seq) - seed + 1):
                entry = counts.setdefault(
                    tuple(t[0] for t in seq[i: i + seed]), [0, 0, 0, 0]
                )
                entry[which] += 1
                entry[2 + which] = i
        runs = []
        for i, j in sorted(
            (e[2], e[3]) for e in counts.values() if e[0] == e[1] == 1
        ):
            if runs and (i, j) == (runs[-1][0] + runs[-1][2] - seed + 1,
                                   runs[-1][1] + runs[-1][2] - seed + 1):
                runs[-1][2] += 1
            else:
                runs.append([i, j, seed])
        # }}}
        # {{{ the heaviest chain of runs in order stays in place; headers
        #     rarely move, so runs holding one weigh much more
        best = []
        for k, (i, j, size) in enumerate(runs):
            weight = size + 100 * sum(
                bool(re.fullmatch(r"#{1,6}|\\(?:sub)*section\*?{.*", t[0]))
                for t in old[i: i + size]
            )
            choice = (weight, None)
            for p in range(k):
                pi, pj, psize = runs[p]
                # (neighbouring runs may share a few tokens, e.g. a
                # blank line)
                if (pi < i and pj < j and pi + psize < i + seed
                        and pj + psize < j + seed
                        and best[p][0] + weight > choice[0]):
                    choice = (best[p][0] + weight, p)
            best.append(choice)
        in_place = set()
        k = max(range(len(runs)), key=lambda q: best[q][0], default=None)
        while k is not None:
            in_place.add(k)
            k = best[k][1]
        # }}}
        # {{{ chain moved runs whose sources and targets are both close
        chains = []
        for k, (i, j, size) in enumerate(runs):
            if k in in_place:
                continue
            for chain in reversed(chains):
                gaps = (i - chain[1], j - chain[3])
                if min(gaps) >= 0 and max(gaps) <= max(4, min(size,
                                                              chain[5])):
                    chain[1:] = [i + size, chain[2], j + size,
                                 chain[4] + size, size]
                    break
            else:
                chains.append([i, i + size, j, j + size, size, size])
        # }}}
        # {{{ grow each chain over neighbouring runs of 2+ equal words,
        #     skipping up to 3 changed words a side, but never into text
        #     that stays in place
        fixed = [set(), set()]
        for k in in_place:
            i, j, size = runs[k]
            fixed[0].update(range(i, i + size))
            fixed[1].update(range(j, j + size))
        for chain in chains:
            for step in (-1, 1):
                while True:
                    for skip_old, skip_new in product(range(4), repeat=2):
                        # first old/new indices past the skipped words
                        i = (chain[0] - 1 - skip_old if step < 0
                             else chain[1] + skip_old)
                        j = (chain[2] - 1 - skip_new if step < 0
                             else chain[3] + skip_new)
                        size = 0
                        while (0 <= i + step * size < len(old)
                               and 0 <= j + step * size < len(new)
                               and i + step * size not in fixed[0]
                               and j + step * size not in fixed[1]
                               and old[i + step * size][0]
                               == new[j + step * size][0]
                               and old[i + step * size][0] not in BREAKS):
                            size += 1
                        if size >= 2:
                            break
                    else:
                        break
                    if step < 0:
                        chain[0] = i - size + 1
                        chain[2] = j - size + 1
                    else:
                        chain[1] = i + size
                        chain[3] = j + size
                    chain[4] += size
        # }}}
        # {{{ do not end a move on a scrap of a line (e.g. the "###" of
        #     the next header) past a meaningful line break
        for chain in chains:
            for k in range(chain[1] - 1,
                           max(chain[0], chain[1] - seed) - 1, -1):
                if old[k][0] in BREAKS:
                    chain[3] -= chain[1] - k
                    chain[4] -= chain[1] - k
                    chain[1] = k
                    break
            for k in range(chain[0], min(chain[1], chain[0] + seed)):
                if old[k][0] in BREAKS:
                    chain[2] += k + 1 - chain[0]
                    chain[4] -= k + 1 - chain[0]
                    chain[0] = k + 1
                    break
        # }}}
        # {{{ accept chains that are long, mostly matching, and that land
        #     away from where they came from: the target falls between
        #     two stretches of in-place text, and the source must lie
        #     outside the base text between them
        spans = []
        for a, b, c, d, matched, _ in sorted(chains, key=lambda q: -q[4]):
            low = max((runs[k][0] + runs[k][2] for k in in_place
                       if runs[k][1] + runs[k][2] <= c), default=0)
            high = min((runs[k][0] for k in in_place
                        if runs[k][1] >= d), default=len(old))
            if matched >= min_move and 2 * matched >= max(b - a, d - c) \
                    and not (a <= high and b >= low) \
                    and not any(a < s[1] and b > s[0]
                                or c < s[3] and d > s[2] for s in spans):
                spans.append((a, b, c, d))
        # }}}
        # {{{ diff what is left, with each moved span as a placeholder
        old_cut, places = [], []
        new_cut = []
        position = 0
        for a, b, c, d in sorted(spans):
            old_cut += old[position:a] + [(f"⟦m{side}.{a}⟧", "", "")]
            places += range(position, a + 1)
            position = b
        old_cut += old[position:]
        places += list(range(position, len(old) + 1))
        position = 0
        for a, b, c, d in sorted(spans, key=lambda s: s[2]):
            new_cut += new[position:c]
            new_cut.append((f"⟦t{side}.{a}⟧", "", new[d - 1][2]))
            position = d
        new_cut += new[position:]
        found, pairs[side] = diff_hunks(old_cut, new_cut, side,
                                        leads[side], places)
        hunks += found
        moves += [
            {"side": side, "a": a, "b": b, "chunk": new[c:d],
             "target": f"⟦t{side}.{a}⟧"}
            for a, b, c, d in spans
        ]
        # }}}
    # {{{ unchanged words take whitespace that either side changed (as git
    #     does for rewrapped lines), preferring local's
    merged_base = list(tokens[0])
    for side in (2, 1):
        following = {(i, j) for i, j, _ in pairs[side]}
        for i, j, token in pairs[side]:
            # only where the next word also matches, so the whitespace
            # sits between the same two words
            if token != tokens[0][i] and (i + 1, j + 1) in following:
                merged_base[i] = token
    tokens[0] = merged_base
    # }}}
    # {{{ Git's conflicts, as base token ranges
    zones = []
    if merged is not None:
        draft, conflicts = conflict_views(merged)
        draft_lead, draft_tokens = tokenize(draft, filetype)
        offsets = []
        position = len(draft_lead)
        for _, word, gap in draft_tokens:
            offsets.append(position)
            position += len(word) + len(gap)
        mapped = {}
        for operation, i1, i2, j1, j2 in minimal_opcodes(
            [t[0] for t in tokens[0]], [t[0] for t in draft_tokens]
        ):
            if operation == "equal":
                mapped.update(zip(range(j1, j2), range(i1, i2)))
        for begin, end in conflicts:
            first = bisect_right(offsets, begin - 1)
            last = bisect_right(offsets, end - 1)
            inside = [mapped[j] for j in range(first, last) if j in mapped]
            if inside:
                zones.append((min(inside), max(inside) + 1))
            else:
                before = [mapped[j] for j in range(first) if j in mapped]
                zones.append((max(before, default=-1) + 1,) * 2)
    # }}}
    # {{{ show a move, with the mover's edits and the other side's
    #     in-place edits, when the other side edited it or it touches a
    #     conflict
    for move in moves:
        a, b = move["a"], move["b"]
        target = next(h for h in hunks
                      if any(t[0] == move["target"] for t in h["tokens"]))
        # (hunks holding the other side's own moves stay where they are)
        inside = [
            h for h in hunks
            if h["side"] != move["side"] and a <= h["start"]
            and h["stop"] <= b and (h["start"] < h["stop"]
                                    or a < h["start"] < b)
            and not any(t[0].startswith("⟦") for t in h["tokens"])
            and not any(m["side"] == h["side"] and h["start"] <= m["a"]
                        and m["b"] <= h["stop"] for m in moves)
        ]
        ends = [
            {k for k, (z0, z1) in enumerate(zones)
             if (a < z1 and b > z0) or (z0 == z1 and a <= z0 <= b)},
            {k for k, (z0, z1) in enumerate(zones)
             if target["start"] <= z1 and target["stop"] >= z0},
        ]
        # a move within one conflict is already shown by that conflict
        if not (inside or ends[0] | ends[1]) or (
            ends[0] and ends[0] == ends[1]
        ):
            continue
        move["text"] = joined(render(
            a, b,
            diff_hunks(tokens[0][a:b], move["chunk"], move["side"], "",
                       list(range(a, b + 1)))[0] + inside,
            True,
        ))
        # first appearance: the source, or the target (several targets
        # can share one hunk, so their order within it counts too)
        move["where"] = (a, 0) if a < target["start"] else (
            target["start"],
            [t[0] for t in target["tokens"]].index(move["target"]),
        )
        hunks = [h for h in hunks if not any(h is x for x in inside)]
    # number the shown moves in hex, in the order they first appear, so
    # gvim can jump between the two ends with *
    for number, move in enumerate(sorted(
        (m for m in moves if "text" in m), key=lambda m: m["where"]
    )):
        move["tag"] = f"{tags[move['side']]} m{number:02x}"
    # }}}
    # {{{ put moved text (or its marks) in place of the placeholders, and
    #     split hunks so what they insert comes before what they delete
    pieces = []
    for hunk in hunks:
        expanded = []
        split = False
        for token in hunk["tokens"]:
            move = next((m for m in moves if m["target"] == token[0]), None)
            if move is None:
                expanded.append(token)
            elif "text" in move:
                expanded.append(("→m", "[" + move["tag"] + "→ "
                                 + move["text"] + "]", token[2]))
                split = True
            else:
                expanded += move["chunk"]
        sources = sorted(
            (m for m in moves if m["side"] == hunk["side"]
             and hunk["start"] <= m["a"] and m["b"] <= hunk["stop"]),
            key=lambda m: m["a"],
        )
        if not (split or sources):
            pieces.append(dict(hunk, tokens=expanded))
            continue
        parts = []
        if expanded:
            # inserted inside the other side's change: put it in front
            position = hunk["start"]
            moved = True
            while moved:
                moved = False
                for other in hunks:
                    if other["side"] != hunk["side"] and \
                            other["start"] < position < other["stop"]:
                        position = other["start"]
                        moved = True
            parts.append(dict(hunk, start=position, stop=position,
                              tokens=expanded))
        position = hunk["start"]
        for move in sources:
            if position < move["a"]:
                stop = move["a"]
                # line breaks next to a shown move mark stay, so the mark
                # keeps the base's layout
                while "text" in move and stop > position \
                        and tokens[0][stop - 1][0] in BREAKS:
                    stop -= 1
                parts.append(dict(hunk, start=position, stop=stop,
                                  tokens=[]))
            parts.append(dict(
                hunk, start=move["a"], stop=move["b"],
                tokens=[(
                    "m→",
                    "[" + move["tag"].replace(" m", " →m") + "]",
                    tokens[0][move["b"] - 1][2],
                )] if "text" in move else [],
            ))
            position = move["b"]
            while "text" in move and position < hunk["stop"] \
                    and tokens[0][position][0] in BREAKS:
                position += 1
        if position < hunk["stop"]:
            parts.append(dict(hunk, start=position, tokens=[]))
        # only the first part starts where the side's token in front of
        # the hunk was, and a move mark keeps the base's line layout
        for k, part in enumerate(parts):
            if k or part["start"] != hunk["start"] or any(
                t[0] == "m→" for t in part["tokens"]
            ):
                part["before"] = None
        pieces += parts
    # }}}
    proposal = leads[0] + "".join(
        word + gap for _, word, gap in render(
            0, len(tokens[0]), pieces, False
        )
    )
    if merged is None:
        return proposal
    # {{{ align the completed merge against the left-pane draft. Keep merge
    #     labels as boundary tokens so their words remain visible to Git's
    #     word matcher, then restore each label after whitespace alignment.
    placeholders = {}

    def mask(text):
        output = []
        position = 0
        while match := re.search(
            r"\[(?:[LR]?[-+]|[LR] m[0-9a-f]+→ |[LR] →m[0-9a-f]+)",
            text[position:],
        ):
            start = position + match.start()
            label_stop = position + match.end()
            depth = 1
            end = label_stop
            while depth and end < len(text):
                depth += (text[end] == "[") - (text[end] == "]")
                end += 1
            if depth:
                break
            start_token = f"PydifftMergeStart{len(placeholders)}Token"
            placeholders[start_token] = text[start:label_stop]
            end_token = f"PydifftMergeEnd{len(placeholders)}Token"
            placeholders[end_token] = "]"
            output.extend((
                text[position:start], start_token,
                mask(text[label_stop:end - 1]), end_token,
            ))
            position = end
        output.append(text[position:])
        return "".join(output)

    draft = conflict_views(merged)[0]
    current = mask(proposal)
    aligned = []
    position = 0
    for result in align_line_breaks(
        draft, current, filetype, width=None, preserve_reference_lines=True,
    ):
        aligned.extend((current[position:result["start"]], result["aligned"]))
        position = result["stop"]
    aligned.append(current[position:])
    current = "".join(aligned)
    for placeholder, marker in placeholders.items():
        current = current.replace(placeholder, marker)
    return current
    # }}}


@register_command(
    "word-wise merge of git conflicts, resolved in gvim -d",
    description=(
        "Word-wise merge of diff3-style git conflicts.\n\n"
        "For each FILE (default: every unmerged file), opens gvim -d with a\n"
        "draft on the left, where every conflict is replaced by its base\n"
        "text, and on the right a word-level merge of git's base, local\n"
        "and remote versions. Clashing edits are shown as\n"
        "[-base][L+local][R+remote]. Text that one side moved while the\n"
        "other edited it is shown as [L →m00] where it came from and\n"
        "[L m00→ text] where it went (moves are numbered in hex), with\n"
        "both sides' edits marked inside\n"
        "(e.g. [L-John][L+Bob]) -- possibly outside git's conflicts.\n"
        "In these windows, dS removes the marker around the cursor,\n"
        "including its tag (e.g. [L+Mark] -> Mark).\n"
        "Edit the left side and save it to resolve: the file is then\n"
        "overwritten with the draft and staged with git add. If the draft\n"
        "is left unchanged, the file stays conflicted.\n"
        "Requires: git config merge.conflictstyle diff3 (or zdiff3).\n"
        "pydifft --add_to_git wmerge installs git wmerge and\n"
        "git mergetool -t pydifft."
    ),
)
def wmerge(arguments):
    filenames = list(arguments)
    if not filenames:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        filenames = [
            str(Path(top) / name)
            for name in subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        ]
        if not filenames:
            print("no conflicted files")
            return
    unresolved = []
    for filename in filenames:
        path = Path(filename)
        with open(path, encoding="utf-8", newline="") as fp:
            text = fp.read()
        # {{{ base, local and remote from git's index stages 1-3
        stages = []
        for number in (1, 2, 3):
            shown = subprocess.run(
                ["git", "show", f":{number}:./{path.name}"],
                cwd=path.parent, capture_output=True,
            )
            if shown.returncode and number > 1:
                raise SystemExit(
                    f"wmerge: {filename} is not an unmerged file in git: "
                    + shown.stderr.decode(errors="replace").strip()
                )
            stages.append(
                "" if shown.returncode
                else shown.stdout.decode("utf-8")
            )
        # }}}
        try:
            draft = conflict_views(text)[0]
            proposal = merge_texts(
                *stages, merged=text,
                filetype="latex" if path.suffix == ".tex" else "markdown",
            )
        except ValueError as exc:
            raise SystemExit(
                f"wmerge: {filename}: "
                + str(exc).replace("FILE", filename)
            ) from None
        with tempfile.TemporaryDirectory(prefix="pydifft-wmerge-") as tmp:
            draft_path = Path(tmp) / ("draft_" + path.name)
            merged_path = Path(tmp) / ("merged_" + path.name)
            script_path = Path(tmp) / "wmerge.vim"
            for target, content in (
                (draft_path, draft),
                (merged_path, proposal),
                # {{{ dS: a surround-style delete that also drops the tag
                (script_path, r"""scriptencoding utf-8
" a merge tag: [L+ [R- [+ [- [L m00→  or [L →m00
let s:tag = '\[\%([LR]\=[-+]\|[LR] m\x\+→ \|[LR] →m\x\+\)'

" highlight every tag and the "]" that closes it, black on red
function! s:Mark() abort
  for id in get(w:, 'merge_marks', [])
    silent! call matchdelete(id)
  endfor
  let w:merge_marks = []
  let here = getcurpos()
  call cursor(1, 1)
  let flags = 'cW'
  while search(s:tag, flags) > 0
    let flags = 'W'
    let [l1, c1] = [line('.'), col('.')]
    let width = len(matchstr(strpart(getline(l1), c1 - 1), '^' . s:tag))
    " searchpair counts nested brackets and, unlike %, ignores quotes
    let [l2, c2] = searchpairpos('\[', '', '\]', 'nW')
    if l2 > 0
      call add(w:merge_marks, matchaddpos('MergeMarker',
            \ [[l1, c1, width], [l2, c2, 1]], 20))
    endif
  endwhile
  call setpos('.', here)
endfunction

" dS: like a surround delete, but also drops the tag
function! s:DeleteMergeMarker() abort
  let here = getcurpos()
  let flags = 'bcW'
  while search(s:tag, flags) > 0
    let flags = 'bW'
    let [l1, c1] = [line('.'), col('.')]
    let [l2, c2] = searchpairpos('\[', '', '\]', 'nW')
    " the nearest tag whose bracket encloses the cursor
    if l2 > here[1] || (l2 == here[1] && c2 >= here[2])
      let width = len(matchstr(strpart(getline(l1), c1 - 1), '^' . s:tag))
      let text = getline(l2)
      call setline(l2, strpart(text, 0, c2 - 1) . strpart(text, c2))
      let text = getline(l1)
      call setline(l1, strpart(text, 0, c1 - 1)
            \ . strpart(text, c1 - 1 + width))
      call cursor(l1, c1)
      call s:Mark()
      return
    endif
  endwhile
  call setpos('.', here)
  echo 'no merge marker around the cursor'
endfunction

highlight MergeMarker guifg=black guibg=red ctermfg=black ctermbg=red
augroup pydifft_wmerge
  autocmd!
  autocmd ColorScheme * highlight MergeMarker
        \ guifg=black guibg=red ctermfg=black ctermbg=red
  windo autocmd TextChanged,TextChangedI <buffer> call s:Mark()
augroup END
windo call s:Mark()
windo nnoremap <buffer> <silent> dS :call <SID>DeleteMergeMarker()<CR>
1wincmd w
"""),
                # }}}
            ):
                with open(target, "w", encoding="utf-8", newline="") as fp:
                    fp.write(content)
            subprocess.run([
                "gvim", "-d", "-f", "-S", str(script_path),
                str(draft_path), str(merged_path),
            ])
            with open(draft_path, encoding="utf-8", newline="") as fp:
                edited = fp.read()
        if edited == draft:
            print(f"{filename}: draft unchanged, left unresolved")
            unresolved.append(filename)
            continue
        leftovers = [
            marker
            for marker in ("[L+", "[R+", "[L-", "[R-", "[-", "[+", "→",
                           "<<<<<<<", ">>>>>>>")
            if marker in edited and marker not in draft
        ]
        if leftovers:
            print(
                f"{filename}: warning, resolution still contains "
                + ", ".join(leftovers)
            )
        with open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(edited)
        subprocess.run(["git", "add", "--", str(path)], check=True)
        print(f"{filename}: resolved and staged")
    if unresolved:
        raise SystemExit(1)
