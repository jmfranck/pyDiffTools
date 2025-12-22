import pickle
from .doc_contents import doc_contents_class
import re

from .command_registry import register_command


def _write_outline_files(all_contents, basename):
    # save the reordered data and user-editable outline sidecar
    with open(f"{basename}_outline.pickle", "wb") as fp:
        pickle.dump(all_contents, fp)
    with open(f"{basename}_outline.md", "w", encoding="utf-8") as fp:
        fp.write(all_contents.outline)


def extract_outline(filename):
    basename = filename.replace(".tex", "")
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
            ):  # do this whether continued open brace from previous line,
                # or if we opened brace on previous
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
    _write_outline_files(all_contents, basename)


def _reorder_from_outline(targetfile, extension, format_type):
    # rebuild a file based on the user-adjusted outline list
    markdownfile = targetfile.replace(extension, "_outline.md")
    picklefile = targetfile.replace(extension, "_outline.pickle")
    if not (
        markdownfile.endswith(".md")
        and picklefile.endswith(".pickle")
        and targetfile.endswith(extension)
    ):
        raise ValueError("pass 1 argument: target file (output)")

    with open(picklefile, "rb") as fp:
        all_contents = pickle.load(fp)
    all_contents.set_format(format_type)
    with open(markdownfile, "r", encoding="utf-8") as fp:
        for thisline in fp:
            all_contents.outline_in_order(thisline.rstrip())
    with open(targetfile, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(str(all_contents))


@register_command(
    "Save tex file as outline, with filename_outline.pickle storing content",
    " and filename_outline.md giving outline.",
)
def xo(arguments):
    assert len(arguments) == 1
    extract_outline(arguments[0])


@register_command(
    "Save markdown file as outline, with filename_outline.pickle storing"
    " content",
    " and filename_outline.md giving outline.",
)
def xomd(arguments):
    assert len(arguments) == 1
    filename = arguments[0]
    # read a markdown file and capture headings while keeping content for
    # reordering
    basename = filename.replace(".md", "")
    header_re = re.compile(r"^(#{1,6})\s+(.*)")
    underline_re = {
        "section": re.compile(r"^={3,}\s*$"),
        "subsection": re.compile(r"^-{3,}\s*$"),
    }

    all_contents = doc_contents_class("markdown")
    previous_line = None
    in_code_block = False
    with open(filename, "r", encoding="utf-8") as fp:
        for thisline in fp:
            stripped = thisline.rstrip("\n")
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                all_contents += thisline
                previous_line = None
                continue
            if in_code_block:
                all_contents += thisline
                continue
            thismatch = header_re.match(stripped)
            if thismatch:
                hashes, thistitle = thismatch.groups()
                level = len(hashes)
                if level == 1:
                    all_contents.start_sec("section", thistitle.strip())
                elif level == 2:
                    all_contents.start_sec("subsection", thistitle.strip())
                elif level == 3:
                    all_contents.start_sec("subsubsection", thistitle.strip())
                elif level == 4:
                    all_contents.start_sec("paragraph", thistitle.strip())
                else:
                    all_contents.start_sec("subparagraph", thistitle.strip())
                all_contents += "\n"
                previous_line = None
                continue
            if previous_line is not None:
                if underline_re["section"].match(stripped):
                    all_contents.start_sec("section", previous_line.strip())
                    previous_line = None
                    continue
                if underline_re["subsection"].match(stripped):
                    all_contents.start_sec("subsection", previous_line.strip())
                    previous_line = None
                    continue
                all_contents += previous_line + "\n"
            previous_line = stripped
        if previous_line:
            all_contents += previous_line + "\n"
    _write_outline_files(all_contents, basename)


@register_command(
    "use the modified filename_outline.md to write reordered text",
    help={"texfile": "TeX file to regenerate from its outline files"},
)
def xoreorder(texfile):
    """Rewrite a TeX file using its saved outline and ordering hints."""

    _reorder_from_outline(texfile, ".tex", "latex")


@register_command(
    "rewrite a markdown file using its saved outline and ordering hints",
    help={"mdfile": "Markdown file to regenerate from its outline files"},
)
def xomdreorder(mdfile):
    _reorder_from_outline(mdfile, ".md", "markdown")


# Provide the previous function name for callers expecting it.
write_reordered = xoreorder
