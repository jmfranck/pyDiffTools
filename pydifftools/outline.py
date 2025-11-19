import pickle
from .doc_contents import doc_contents_class
import re

from .command_registry import register_command


def extract_outline(filename):
    basename = filename.replace(".tex", "")
    section_re = re.compile(
        r"\\(paragraph|subsubsection|subsection|section)\{"
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
    with open(f"{basename}_outline.pickle", "wb") as fp:
        pickle.dump(all_contents, fp)
    with open(f"{basename}_outline.md", "w", encoding="utf-8") as fp:
        fp.write(all_contents.outline)


@register_command(
    "use the modified filename_outline.md to write reordered text",
    help={"texfile": "TeX file to regenerate from its outline files"},
)
def xoreorder(texfile):
    """Rewrite a TeX file using its saved outline and ordering hints."""

    markdownfile = texfile.replace(".tex", "_outline.md")
    picklefile = texfile.replace(".tex", "_outline.pickle")
    if not (
        markdownfile.endswith(".md")
        and picklefile.endswith(".pickle")
        and texfile.endswith(".tex")
    ):
        raise ValueError("pass 1 argument: texfile (output)")

    with open(picklefile, "rb") as fp:
        all_contents = pickle.load(fp)
    with open(markdownfile, "r", encoding="utf-8") as fp:
        for thisline in fp:
            all_contents.outline_in_order(thisline.rstrip())
    with open(texfile, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(str(all_contents))


# Provide the previous function name for callers expecting it.
write_reordered = xoreorder
