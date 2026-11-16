from difflib import SequenceMatcher
from .line_alignment import align_line_breaks
from .wrapping_options import (
    DEFAULT_WIDTH, DEFAULT_DESIRED_WIDTH,
    DEFAULT_TRAILING_DEPENDENT_PHRASE,
)
from .wrap_sentences import (
    markdown_blocks,
    wrap_blocks,
)


def run(
    arguments,
    wrapnumber=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
    desired_width=DEFAULT_DESIRED_WIDTH,
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
            desired_width,
        )
    else:
        result = match_text(
            text1, text2, filetype, wrapnumber, trailing_dependent_phrase,
            desired_width,
        )
    with open(arguments[1], "w", encoding="utf-8") as fp:
        fp.write(result)


def match_blocks(
    old,
    new,
    width=DEFAULT_WIDTH,
    trailing_dependent_phrase=DEFAULT_TRAILING_DEPENDENT_PHRASE,
    desired_width=DEFAULT_DESIRED_WIDTH,
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
                                max(1, desired_width - target.margin),
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
                            desired_width,
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
    desired_width=DEFAULT_DESIRED_WIDTH,
):
    """Align reference lines and wrap only overflowing edited prose."""
    results = align_line_breaks(
        text1,
        text2,
        filetype,
        width=fallback_width,
        punctuation_slop=trailing_dependent_phrase,
        preserve_reference_lines=True,
        desired_width=desired_width,
    )
    pieces = []
    position = 0
    for result in results:
        pieces.extend((text2[position : result["start"]], result["aligned"]))
        position = result["stop"]
    pieces.append(text2[position:])
    return "".join(pieces)
