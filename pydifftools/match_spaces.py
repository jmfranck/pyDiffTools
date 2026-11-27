from .line_alignment import align_line_breaks
from .wrapping_options import (
    DEFAULT_WIDTH, DEFAULT_DESIRED_WIDTH,
    DEFAULT_TRAILING_DEPENDENT_PHRASE,
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
    results = align_line_breaks(
        text1,
        text2,
        filetype,
        width=wrapnumber,
        punctuation_slop=trailing_dependent_phrase,
        preserve_reference_lines=True,
        desired_width=desired_width,
    )
    if all(result["aligned"] == result["before"] for result in results):
        return
    pieces = []
    position = 0
    for result in results:
        pieces.extend((text2[position : result["start"]], result["aligned"]))
        position = result["stop"]
    pieces.append(text2[position:])
    with open(arguments[1], "w", encoding="utf-8") as fp:
        fp.writelines(pieces)
