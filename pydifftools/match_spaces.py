from difflib import SequenceMatcher
from bisect import bisect_left
import math
from .line_alignment import align_line_breaks
from .wrapping_options import (
    DEFAULT_WIDTH,
    DEFAULT_TRAILING_DEPENDENT_PHRASE,
)
from .wrap_sentences import (
    classify_lines,
    markdown_blocks,
    wrap_blocks,
)


def run(
    arguments,
    wrapnumber=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
):
    with open(arguments[0], encoding="utf-8") as fp:
        text1 = fp.read()
    with open(arguments[1], encoding="utf-8") as fp:
        text2 = fp.read()
    filetype = (
        "markdown" if arguments[1].endswith((".md", ".qmd")) else "latex"
    )
    if filetype == "markdown":
        result = match_blocks(
            markdown_blocks(text1),
            markdown_blocks(text2),
            wrapnumber,
            trailing_dependent_phrase,
        )
    else:
        result = match_text(
            text1, text2, filetype, wrapnumber, trailing_dependent_phrase
        )
    with open(arguments[1], "w", encoding="utf-8") as fp:
        fp.write(result)


def match_blocks(
    old,
    new,
    width=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
):
    """Match container bodies without treating markers as words."""
    output = []
    matcher = SequenceMatcher(
        None, [b.kind for b in old], [b.kind for b in new]
    )
    for operation, a, b, c, d in matcher.get_opcodes():
        if operation == "equal":
            for reference, target in zip(old[a:b], new[c:d]):
                if target.kind == "raw" or reference.text == target.text:
                    output.append(target.text)
                elif target.children:
                    output.append(
                        target.restore(
                            match_blocks(
                                reference.children,
                                target.children,
                                max(1, width - target.margin),
                                trailing_dependent_phrase,
                            )
                        )
                    )
                else:
                    output.append(
                        match_text(
                            reference.text,
                            target.text,
                            "markdown",
                            width,
                            trailing_dependent_phrase,
                        )
                    )
        else:
            output.append(
                wrap_blocks(new[c:d], width, trailing_dependent_phrase)
            )
    return "".join(output)


def match_text(
    text1,
    text2,
    filetype,
    fallback_width=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
):
    """Align reference lines and wrap only overflowing edited prose."""
    text2 = text2.replace("\u00a0", " ").replace("\u2004", " ")
    # {{{ choose the nearby reference width before any line linting
    reference_lines = classify_lines(text1, filetype)
    prose_rows = [
        row
        for row, (allowed, line) in enumerate(reference_lines)
        if allowed and line.strip()
    ]

    def reference_width(row, restored, joined):
        closest = bisect_left(prose_rows, row)
        nearby = sorted(
            prose_rows[max(0, closest - 10) : closest + 10],
            key=lambda number: (abs(number - row), number),
        )[:10]
        widths = sorted(
            len(reference_lines[number][1].rstrip("\n")) for number in nearby
        )
        local = (
            min(fallback_width, widths[math.ceil(0.75 * len(widths)) - 1])
            if len(widths) >= 2
            else fallback_width
        )
        return (
            local
            if any(
                len(line) > (local if joined else 1.5 * local)
                for line in restored.splitlines()
            )
            else fallback_width
        )

    # }}}
    results = align_line_breaks(
        text1,
        text2,
        filetype,
        width=reference_width,
        punctuation_slop=trailing_dependent_phrase,
        preserve_reference_lines=True,
    )
    pieces = []
    position = 0
    for result in results:
        pieces.extend((text2[position : result["start"]], result["aligned"]))
        position = result["stop"]
    pieces.append(text2[position:])
    return "".join(pieces)
