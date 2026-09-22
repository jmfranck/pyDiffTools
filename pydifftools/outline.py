import os
import pickle
from .doc_contents import doc_contents_class
import re

from .command_registry import register_command

_FORMAT_BY_EXTENSION = {
    ".tex": "latex",
    ".md": "markdown",
    ".qmd": "markdown",
}


def _outline_paths(filename):
    # determine the format from the extension, along with the sidecar files
    stem, extension = os.path.splitext(filename)
    if extension.lower() not in _FORMAT_BY_EXTENSION:
        raise ValueError(
            f"don't know how to outline {filename}: expected one of "
            + ", ".join(_FORMAT_BY_EXTENSION)
        )
    return (
        _FORMAT_BY_EXTENSION[extension.lower()],
        f"{stem}_outline.md",
        f"{stem}_outline.pickle",
    )


@register_command(
    "Save a tex or markdown file as an outline, with"
    " filename_outline.pickle storing content",
    " and filename_outline.md giving outline.  The format is determined"
    " from the file extension.",
    help={"filename": "TeX or markdown file to outline"},
    filename_extensions={"filename": list(_FORMAT_BY_EXTENSION)},
)
def xo(filename):
    format_type, markdownfile, picklefile = _outline_paths(filename)
    if format_type == "latex":
        # {{{ read a tex file and capture sectioning commands
        section_re = re.compile(
            r"\\(paragraph|subparagraph|subsubsection|subsection|section)\{"
        )

        all_contents = doc_contents_class()
        bracelevel = 0
        with open(filename, "r", encoding="utf-8") as fp:
            for thisline in fp:
                if bracelevel == 0:
                    thismatch = section_re.match(thisline)
                    if thismatch:
                        sectype = thismatch.groups()[0]
                        bracelevel = 1
                        all_contents += thisline[: thismatch.start()]
                        escaped = False
                        thistitle = ""
                    else:
                        all_contents += thisline
                if (
                    bracelevel > 0
                ):  # do this whether continued open brace from previous
                    # line, or if we opened brace on previous
                    for n, j in enumerate(thisline[thismatch.end() :]):
                        if escaped:
                            escaped = False
                        elif j == "\\":
                            escaped = True
                        elif j == "{":
                            bracelevel += 1
                        elif j == "}":
                            bracelevel -= 1
                        if bracelevel > 0:
                            thistitle += j
                        else:
                            all_contents.start_sec(sectype, thistitle)
                            all_contents += thisline[thismatch.end() + n + 1 :]
                            break
                    else:  # hit the end of the line without the break
                        thisline += "\n"
        # }}}
    else:
        # {{{ read a markdown file and capture headings while keeping
        #     content for reordering
        header_re = re.compile(r"^(#{1,6})\s+(.*)")
        underline_re = {
            "section": re.compile(r"^={3,}\s*$"),
            "subsection": re.compile(r"^-{3,}\s*$"),
        }
        section_by_level = {
            1: "section",
            2: "subsection",
            3: "subsubsection",
            4: "paragraph",
        }

        all_contents = doc_contents_class("markdown")
        # previous_line holds the raw text of the prior line, since it
        # might turn out to be a setext heading
        previous_line = None
        in_code_block = False
        in_front_matter = False
        with open(filename, "r", encoding="utf-8") as fp:
            for lineno, thisline in enumerate(fp):
                stripped = thisline.rstrip("\n")
                if lineno == 0 and stripped == "---":
                    in_front_matter = True
                    all_contents += thisline
                    continue
                if in_front_matter:
                    # YAML front matter is kept verbatim in the header
                    all_contents += thisline
                    if stripped in ("---", "..."):
                        in_front_matter = False
                    continue
                if stripped.startswith("```"):
                    in_code_block = not in_code_block
                if in_code_block or stripped.startswith("```"):
                    if previous_line is not None:
                        all_contents += previous_line
                        previous_line = None
                    all_contents += thisline
                    continue
                thismatch = header_re.match(stripped)
                if thismatch:
                    if previous_line is not None:
                        all_contents += previous_line
                        previous_line = None
                    hashes, thistitle = thismatch.groups()
                    all_contents.start_sec(
                        section_by_level.get(len(hashes), "subparagraph"),
                        thistitle.strip(),
                    )
                    continue
                if previous_line is not None and previous_line.strip():
                    if underline_re["section"].match(stripped):
                        all_contents.start_sec(
                            "section", previous_line.strip()
                        )
                        previous_line = None
                        continue
                    if underline_re["subsection"].match(stripped):
                        all_contents.start_sec(
                            "subsection", previous_line.strip()
                        )
                        previous_line = None
                        continue
                if previous_line is not None:
                    all_contents += previous_line
                previous_line = thisline
            if previous_line is not None:
                all_contents += previous_line
        # }}}
    # save the parsed data and user-editable outline sidecar
    with open(picklefile, "wb") as fp:
        pickle.dump(all_contents, fp)
    with open(markdownfile, "w", encoding="utf-8") as fp:
        fp.write(all_contents.outline)


@register_command(
    "use the modified filename_outline.md to write reordered text"
    " (tex or markdown, determined from the file extension)",
    help={"filename": "TeX or markdown file to regenerate from its outline"},
    filename_extensions={"filename": list(_FORMAT_BY_EXTENSION)},
)
def xore(filename):
    """Rewrite a file using its saved outline and ordering hints."""
    format_type, markdownfile, picklefile = _outline_paths(filename)
    with open(picklefile, "rb") as fp:
        all_contents = pickle.load(fp)
    all_contents.set_format(format_type)
    with open(markdownfile, "r", encoding="utf-8") as fp:
        for thisline in fp:
            all_contents.outline_in_order(thisline.rstrip())
    # build the text before opening the target, so that an error (e.g. a
    # section missing from the outline) doesn't leave an empty file
    reordered = str(all_contents)
    with open(filename, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(reordered)


# Provide the previous function name for callers expecting it.
write_reordered = xore
