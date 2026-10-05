"""Common defaults and CLI definitions for source wrapping commands."""

DEFAULT_WIDTH = 79
DEFAULT_TRAILING_DEPENDENT_PHRASE = 20

WRAPPING_ARGUMENTS = {
    "wrapnumber": {
        "help": "Maximum source line width in characters.",
    },
    "trailing_dependent_phrase": {
        "flags": ["--trailing-dependent-phrase", "--punctuation-slop"],
        "help": (
            "Break at punctuation within this many characters of the "
            "maximum width, including on lines that still fit (default: "
            "20; 0 disables this rule)."
        ),
    },
}
