import os
import re
import subprocess
import sys
import itertools
from dataclasses import dataclass, field

from .command_registry import register_command
from .wrapping_options import (
    DEFAULT_TRAILING_DEPENDENT_PHRASE, WRAPPING_ARGUMENTS,
)

DISPLAY_MATH = re.compile(r"(?<!\\)(?:\\\\)*(\$\$)")

# Shared with wrchk so the two commands agree on what a paragraph, a
# sentence boundary, and a LaTeX structural macro look like.
PARAGRAPH_SPLIT = re.compile(r"(\n(?:[ \t]*\n)+)")
# A sentence ends at a '.', '!' or '?' preceded by 3 characters that are
# not themselves sentence-ending punctuation -- a crude guard against
# treating "e.g." or "..." as a sentence break.
SENTENCE_END = r"[^.!?]{3}[.!?]"
SENTENCE_SPLIT = re.compile("(" + SENTENCE_END + r")[ \n]")
SENTENCE_BOUNDARY = re.compile("(" + SENTENCE_END + r")([ \n])")
# A word is a run of non-space characters, except that an attribute block
# attached to a figure's closing ")" (or any "{#id ...}" block) stays inside
# the word, so a break never lands inside a pandoc-crossref marker.
WORD = re.compile(r"(?:(?<=\))\{[^}]*\}|\{#[^}]*\}|\S)+")
# A pandoc-crossref marker must directly follow the closing "$$" of its
# equation or the closing ")" of its figure, and must stay on one line.
DETACHED_CROSSREF = re.compile(
    r"(?:(?<!\\)\$\$|\))(?P<gap>[ \t]*\n?[ \t]*)(?=\{#(?:eq|fig):)"
    r"|(?P<marker>\{#(?:eq|fig):[^}\n]*\n[^}]*\})"
)
# Comment tags are two initials and "com" (<JFcom>, <JFcom-left>, ...); the
# comment filter passes a misspelling such as <JFcomm> through as raw HTML.
MISSPELLED_COMMENT_TAG = re.compile(
    r"<(/?)([A-Za-z]{2})comm(?:ent)?(-left|-right)?>", re.IGNORECASE
)
LATEX_MACRO_SPLIT = re.compile(
    r"(\\(?:begin|end|usepackage|newcommand|section"
    r"|subsection|subsubsection|paragraph|input){[^}]*})"
)


@dataclass
class MarkdownBlock:
    """A source span with optional children stripped of an outer marker."""

    text: str
    kind: str = "prose"
    prefix: str = ""
    continuation: str = ""
    children: list = field(default_factory=list)

    @property
    def margin(self):
        return max(
            len(self.prefix.expandtabs(4)),
            len(self.continuation.expandtabs(4)),
        )

    def restore(self, body):
        output = []
        paragraph_start = True
        classified = classify_lines(body)
        for idx, (allowed, line) in enumerate(classified):
            prefix = self.prefix if idx == 0 else self.continuation
            if self.kind == "lazy_quote":
                if (
                    paragraph_start
                    or not allowed
                    or not line.strip()
                    or line.startswith(("    ", "\t"))
                    or re.match(r" {0,3}(?:>|[-+*] |[0-9]+[.)] )", line)
                ):
                    prefix = self.prefix
            if not line.strip():
                prefix = prefix.rstrip() if ">" in prefix else ""
            output.append(prefix + line)
            paragraph_start = not line.strip()
        return "".join(output)


def markdown_blocks(text):
    """Split Markdown containers recursively, keeping original source spans."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    allowed = [flag for flag, _ in classify_lines(text, strict=False)]
    marker = re.compile(
        r"^( {0,3})(>|:|[-+*]|[0-9]+[.)])([ \t]+|(?<=>)|(?=\n?$))"
    )
    blocks = []
    idx = 0
    plain_start = 0
    while idx < len(lines):
        match = marker.match(lines[idx])
        if match and match[2] == ":" and not allowed[idx]:
            before = idx - 1
            while before >= 0 and not lines[before].strip():
                before -= 1
            if before < 0 or not allowed[before]:
                match = None
        if not match:
            if (
                (idx == 0 or not lines[idx - 1].strip())
                and lines[idx].startswith(("    ", "\t"))
                and lines[idx].strip()
            ):
                if idx > plain_start:
                    blocks.append(
                        MarkdownBlock("".join(lines[plain_start:idx]))
                    )
                start = idx
                while idx < len(lines) and (
                    not lines[idx].strip()
                    or lines[idx].startswith(("    ", "\t"))
                ):
                    idx += 1
                blocks.append(MarkdownBlock("".join(lines[start:idx]), "raw"))
                plain_start = idx
                continue
            if not allowed[idx]:
                # Skip an outer protected span before inspecting its contents.
                idx += 1
                while idx < len(lines) and not allowed[idx]:
                    idx += 1
                continue
            idx += 1
            continue
        token = match[2]
        # A horizontal rule is not a list item; a colon needs a term.
        if re.fullmatch(r" {0,3}(?:[-*][ \t]*){3,}\n?", lines[idx]) or (
            token == ":" and not any(line.strip() for line in lines[:idx])
        ):
            idx += 1
            continue
        start = idx
        if token == ":":
            term_end = start
            while term_end > plain_start and not lines[term_end - 1].strip():
                term_end -= 1
            if term_end > plain_start:
                term_start = term_end - 1
                if term_start > plain_start:
                    blocks.append(
                        MarkdownBlock("".join(lines[plain_start:term_start]))
                    )
                blocks.append(
                    MarkdownBlock("".join(lines[term_start:start]), "raw")
                )
                plain_start = start
        if start > plain_start:
            blocks.append(MarkdownBlock("".join(lines[plain_start:start])))
        prefix = match[0]
        margin = len(prefix.expandtabs(4))
        continuation = " " * (max(4, margin) if token == ":" else margin)
        body = [lines[start][match.end() :]]
        quote = token == ">"
        explicit = True
        quote_lines = 1
        lazy_indent = None
        idx += 1
        # {{{ collect the container body, retaining indentation inside it
        while idx < len(lines):
            line = lines[idx]
            next_marker = marker.match(line)
            if quote and next_marker and next_marker[2] == ">":
                quote_lines += 1
                # Only one optional space belongs to the quote marker.
                cut = len(next_marker[1]) + 1
                if line[cut : cut + 1] == " ":
                    cut += 1
                body.append(line[cut:])
                idx += 1
                continue
            if not line.strip():
                following = idx + 1
                while following < len(lines) and not lines[following].strip():
                    following += 1
                if following == len(lines):
                    break
                future = lines[following]
                if quote:
                    future_marker = marker.match(future)
                    continues = future_marker and future_marker[2] == ">"
                else:
                    continues = future.startswith(
                        continuation
                    ) or future.startswith("\t")
                if not continues:
                    break
                body.extend(lines[idx:following])
                idx = following
                continue
            if not quote and (
                line.startswith(continuation) or line.startswith("\t")
            ):
                cut = 1 if line.startswith("\t") else len(continuation)
                body.append(line[cut:])
            elif next_marker or not allowed[idx] or not body[-1].strip():
                break
            else:
                body.append(line)
                if quote:
                    explicit = False
                    indentation = line[: len(line) - len(line.lstrip(" \t"))]
                    if lazy_indent is None:
                        lazy_indent = indentation
                    elif not indentation.startswith(lazy_indent):
                        lazy_indent = ""
            idx += 1
        # }}}
        if quote:
            # Preserve relative indentation (code, lists, nested quotations).
            prefix = match[1] + ">" + (" " if match[3].startswith(" ") else "")
            body[0] = lines[start][len(prefix) :]
            indentation = min(
                (
                    len(line) - len(line.lstrip(" "))
                    for line in body
                    if line.strip()
                ),
                default=0,
            )
            # Up to three common spaces are presentation indentation;
            # four spaces introduce an indented code block in Pandoc.
            if 0 < indentation < 4:
                prefix += " " * indentation
                body = [
                    line[indentation:] if line.strip() else line
                    for line in body
                ]
            explicit = explicit and quote_lines > 1
            continuation = prefix if explicit else lazy_indent or ""
            if continuation and not explicit:
                body = [body[0]] + [
                    (
                        line[len(continuation) :]
                        if line.startswith(continuation)
                        else line
                    )
                    for line in body[1:]
                ]
            kind = "quote" if explicit else "lazy_quote"
        else:
            kind = "definition" if token == ":" else "list"
        blocks.append(
            MarkdownBlock(
                "".join(lines[start:idx]),
                kind,
                prefix,
                continuation,
                markdown_blocks("".join(body)),
            )
        )
        plain_start = idx
    if plain_start < len(lines):
        blocks.append(MarkdownBlock("".join(lines[plain_start:])))
    return blocks


def wrap_blocks(blocks, wrapnumber, punctuation_slop=20, indent_amount=0):
    """Wrap container bodies with the available width, then restore markers."""
    output = []
    for block in blocks:
        if block.kind == "raw":
            output.append(block.text)
        elif block.children:
            output.append(
                block.restore(
                    wrap_blocks(
                        block.children,
                        max(1, wrapnumber - block.margin),
                        punctuation_slop,
                        indent_amount,
                    )
                )
            )
        else:
            classified = classify_lines(block.text, normalize_math=True)
            for allowed, group in itertools.groupby(
                classified, key=lambda x: x[0]
            ):
                content = "".join(line for _, line in group)
                output.append(
                    wrap_prose(
                        content,
                        wrapnumber,
                        punctuation_slop,
                        indent_amount=indent_amount,
                    )
                    if allowed
                    else content
                )
    return "".join(output)


def match_paren(thistext, pos, opener="{"):
    closerdict = {
        "{": "}",
        "(": ")",
        "[": "]",
        "$$": "$$",
        "~~~": "~~~",
        "<!--": "-->",
    }
    if opener in closerdict.keys():
        closer = closerdict[opener]
    else:
        m = re.match(r"<(\w+)", opener)
        assert m
        closer = "</" + m.groups()[0]
    if thistext[pos : pos + len(opener)] == opener:
        parenlevel = 1
    else:
        raise ValueError(
            f"You aren't starting on a '{opener}':"
            + thistext[:pos]
            + ">>>>>"
            + thistext[pos:]
        )
    while parenlevel > 0 and pos < len(thistext):
        pos += 1
        if thistext[pos : pos + len(closer)] == closer:
            if thistext[pos - 1] != "\\":
                parenlevel -= 1
        elif thistext[pos : pos + len(opener)] == opener:
            if thistext[pos - 1] != "\\":
                parenlevel += 1
    if pos == len(thistext):
        raise RuntimeError(
            f"hit end of file without closing {opener} with {closer}\n"
            "here is the offending text!:\n" + ("=" * 30) + thistext
        )
    return pos


def classify_lines(
    text,
    filetype="markdown",
    normalize_math=False,
    strict=True,
):
    """Return (wrappable, line) pairs with original line endings and text."""
    lines = text.splitlines(keepends=True)
    wrappable = [True] * len(lines)
    # {{{ exclude structural blocks before considering paragraphs or math
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        end = idx
        opener = None
        match = None
        if filetype == "markdown":
            fence = re.match(r"^[ \t]*(\x60{3,}|~{3,})", line)
            if fence:
                delimiter = fence[1]
                end = idx + 1
                while end < len(lines):
                    if re.fullmatch(
                        r"[ \t]*"
                        + re.escape(delimiter[0])
                        + "{"
                        + str(len(delimiter))
                        + r",}[ \t]*\n?",
                        lines[end],
                    ):
                        break
                    end += 1
            elif idx == 0 and line.strip() in ("---", "..."):
                end = idx + 1
                while end < len(lines) and lines[end].strip() not in (
                    "---",
                    "...",
                ):
                    end += 1
                if end == len(lines):
                    idx += 1
                    continue
            elif re.match(r"^[ ]{0,3}#{1,6}(?:\s|$)", line):
                pass
            else:
                idx += 1
                continue
        else:
            match = re.match(
                r"\\(?:section|subsection|subsubsection|paragraph|"
                r"newcommand|input)\*?{",
                line,
            )
            if match:
                opener = "{"
            else:
                environment = re.search(r"\\begin{(equation|align)\*?}", line)
                if not environment:
                    idx += 1
                    continue
                closing = environment[0].replace(r"\begin", r"\end")
                while end < len(lines) and closing not in lines[end]:
                    end += 1
                if end == len(lines):
                    raise RuntimeError(
                        "didn't find closing line for environment"
                    )
        if opener:
            remaining = "".join(lines[idx:])
            pos = match.start() if opener.startswith("<") else match.end() - 1
            stop = match_paren(remaining, pos, opener)
            end = idx + remaining[:stop].count("\n")
        end = min(end + 1, len(lines))
        wrappable[idx:end] = [False] * (end - idx)
        idx = end
    # }}}
    if filetype == "markdown":
        # {{{ recognize table separators and preserve complete table spans
        columns = re.compile(r"^[ \t]*-+(?:[ \t]+-+)+[ \t]*$")
        rule = re.compile(r"^[ \t]*-+[ \t]*$")
        pipe = re.compile(
            r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*"
            r"(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
        )
        grid = re.compile(r"^[ \t]*\+(?:[-=:]+\+)+[ \t]*$")
        idx = 0
        while idx < len(lines):
            if not wrappable[idx]:
                idx += 1
                continue
            line = lines[idx].rstrip("\n")
            start = idx
            end = idx + 1
            if "|" in line and pipe.fullmatch(line):
                if idx and wrappable[idx - 1] and "|" in lines[idx - 1]:
                    start -= 1
                while (
                    end < len(lines) and wrappable[end] and "|" in lines[end]
                ):
                    end += 1
            elif grid.fullmatch(line):
                while (
                    end < len(lines)
                    and wrappable[end]
                    and (
                        lines[end].lstrip().startswith("|")
                        or grid.fullmatch(lines[end].rstrip("\n"))
                    )
                ):
                    end += 1
            elif columns.fullmatch(line):
                # A header may occupy several lines after a full-width rule.
                before = idx - 1
                while (
                    before >= 0 and wrappable[before] and lines[before].strip()
                ):
                    if rule.fullmatch(lines[before].rstrip("\n")):
                        start = before
                        break
                    before -= 1
                else:
                    if idx and wrappable[idx - 1] and lines[idx - 1].strip():
                        start = idx - 1
                # A closing rule permits blank lines between multiline rows.
                closing = end
                while closing < len(lines) and wrappable[closing]:
                    candidate = lines[closing].rstrip("\n")
                    if candidate.strip() == line.strip() or (
                        start < idx
                        and rule.fullmatch(lines[start].rstrip("\n"))
                        and rule.fullmatch(candidate)
                    ):
                        end = closing + 1
                        break
                    if re.match(r"^[ \t]*(?:[Tt]able:|:)\s", candidate):
                        break
                    if (
                        closing > idx + 1
                        and not lines[closing - 1].strip()
                        and candidate.strip()
                        and not re.search(r" {2,}|\t", candidate)
                    ):
                        break
                    closing += 1
                if end == idx + 1:
                    while (
                        end < len(lines)
                        and wrappable[end]
                        and lines[end].strip()
                    ):
                        end += 1
            else:
                idx += 1
                continue
            if end == idx + 1 and start == idx:
                idx += 1
                continue
            # Include an adjacent caption paragraph on either side.
            for direction in (-1, 1):
                pos = start - 1 if direction == -1 else end
                while 0 <= pos < len(lines) and not lines[pos].strip():
                    pos += direction
                if direction == -1:
                    first = pos
                    while (
                        first > 0
                        and lines[first - 1].strip()
                        and wrappable[first - 1]
                    ):
                        first -= 1
                    if first >= 0 and re.match(
                        r"^[ \t]*(?:[Tt]able:|:)\s", lines[first]
                    ):
                        start = first
                elif pos < len(lines) and re.match(
                    r"^[ \t]*(?:[Tt]able:|:)\s", lines[pos]
                ):
                    while (
                        pos < len(lines)
                        and wrappable[pos]
                        and lines[pos].strip()
                    ):
                        pos += 1
                    end = pos
            wrappable[start:end] = [False] * (end - start)
            idx = end
        for idx in range(len(lines) - 1):
            if wrappable[idx] and wrappable[idx + 1] and lines[idx].strip():
                if re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*\n?", lines[idx + 1]):
                    wrappable[idx : idx + 2] = [False, False]
        # }}}
        # {{{ preserve figures and HTML outside tables and math
        idx = 0
        in_math = False
        while idx < len(lines):
            if not wrappable[idx] and not in_math:
                idx += 1
                continue
            line = lines[idx]
            dollars = list(DISPLAY_MATH.finditer(line))
            match = re.search(r"!\[.*?\]\(|<(\w+)(?:\s[^>]*)?>", line)
            if in_math or (
                dollars and (not match or dollars[0].start() < match.start())
            ):
                wrappable[idx] = True
                if len(dollars) % 2:
                    in_math = not in_math
            elif match:
                opener = "<" + match[1] if match[1] else "("
                pos = match.start() if match[1] else match.end() - 1
                remaining = "".join(lines[idx:])
                try:
                    stop = match_paren(remaining, pos, opener)
                except RuntimeError:
                    if strict:
                        raise
                    # Container prefixes can hide a fence around literal HTML.
                    # Validate after removing those prefixes instead.
                    idx += 1
                    continue
                end = idx + remaining[:stop].count("\n") + 1
                wrappable[idx:end] = [False] * (end - idx)
                idx = end
                continue
            idx += 1
        # }}}
    # {{{ isolate display math only in otherwise wrappable content
    result = []
    for allowed, group in itertools.groupby(
        zip(wrappable, lines), lambda x: x[0]
    ):
        content = "".join(line for _, line in group)
        if not allowed:
            result.extend(
                (False, line) for line in content.splitlines(keepends=True)
            )
            continue
        delimiters = list(DISPLAY_MATH.finditer(content))
        offset = 0
        for number in range(0, len(delimiters), 2):
            opening = delimiters[number]
            closing = (
                delimiters[number + 1]
                if number + 1 < len(delimiters)
                else None
            )
            start = opening.start(1)
            stop = closing.end() if closing else len(content)
            if stop <= offset:
                continue
            if normalize_math:
                prefix = content[offset:start]
                if prefix and not prefix.endswith("\n"):
                    prefix += "\n"
                result.extend(
                    (True, line) for line in prefix.splitlines(keepends=True)
                )
                body = content[
                    opening.end() : closing.start(1) if closing else stop
                ]
                equation = "$$"
                if not body.startswith("\n"):
                    equation += "\n"
                equation += body
                if closing:
                    if not equation.endswith("\n"):
                        equation += "\n"
                    equation += "$$"
                    # keep a pandoc-crossref marker on its closing "$$"
                    marker = re.match(r"\{#eq:[^}]*\}", content[stop:])
                    if marker:
                        equation += marker[0]
                        stop += marker.end()
                if stop < len(content):
                    equation += "\n"
                    if content[stop] == "\n":
                        stop += 1
                result.extend(
                    (False, line)
                    for line in equation.splitlines(keepends=True)
                )
            else:
                start = max(offset, content.rfind("\n", 0, start) + 1)
                newline = content.find("\n", stop)
                stop = len(content) if newline == -1 else newline + 1
                result.extend(
                    (True, line)
                    for line in content[offset:start].splitlines(keepends=True)
                )
                result.extend(
                    (False, line)
                    for line in content[start:stop].splitlines(keepends=True)
                )
            offset = stop
        result.extend(
            (True, line) for line in content[offset:].splitlines(keepends=True)
        )
    return result
    # }}}


def _math_boundaries(words):
    """Word indices adjoining a paired inline-math run in a word list.

    wrap_prose and check_prose both prefer to break lines at these
    boundaries rather than splitting an inline math expression.
    """
    boundaries = set()
    in_math = False
    opening_word = None
    for j, word in enumerate(words):
        for dollar in re.finditer(r"(?<!\$)\$(?!\$)", word):
            pos = dollar.start()
            if (len(word[:pos]) - len(word[:pos].rstrip("\\"))) % 2:
                continue
            if not in_math:
                opening_word = j if pos == 0 else None
            else:
                if opening_word is not None and opening_word > 0:
                    boundaries.add(opening_word - 1)
                if pos == len(word) - 1:
                    boundaries.add(j)
            in_math = not in_math
    return boundaries


def _next_break(words, wrapnumber, punctuation_slop, boundaries, offset):
    """Index of the last word wr would keep on the line starting here.

    Shared by wrap_prose (which then emits that line) and check_prose
    (which replays the same choice to see if a source line agrees).
    """
    # counts[j] - 1 is the length of the line holding words[: j + 1]
    counts = list(itertools.accumulate(len(word) + 1 for word in words))
    # the last word that fits within the width (or the first word, if even
    # that is too long)
    upto = max(
        [j for j, count in enumerate(counts) if count - 1 <= wrapnumber]
        or [0]
    )
    # prefer to end the line on a clause (comma, paren, dash, ...) or at an
    # inline-math boundary within punctuation_slop of the maximum width.
    # This applies even when the short dependent phrase still fits.
    candidates = [
        j
        for j, word in enumerate(words[: upto + 1])
        if (
            word[-1] in ",;:)-–—"
            or (j + 1 < len(words) and words[j + 1].startswith("("))
            or offset + j in boundaries
        )
        and j < len(words) - 1
        and 0 <= wrapnumber - (counts[j] - 1) <= punctuation_slop
    ]
    return max(candidates) if candidates else upto


def wrap_prose(
    text,
    wrapnumber=45,
    punctuation_slop=20,
    filetype="markdown",
    indent_amount=0,
):
    """Wrap prose with sentence and punctuation rules for both commands."""
    output = []
    # Keep paragraph separators and the boundary newlines next to exclusions.
    for paragraph in PARAGRAPH_SPLIT.split(text):
        if not paragraph.strip():
            output.append(paragraph)
            continue
        leading = "\n" if paragraph.startswith("\n") else ""
        trailing = "\n" if paragraph.endswith("\n") else ""
        parts = SENTENCE_SPLIT.split(paragraph.strip("\n"))
        sentences = [
            parts[j] + (parts[j + 1] if j + 1 < len(parts) else "")
            for j in range(0, len(parts), 2)
        ]
        sentences = [
            part
            for sentence in sentences
            for part in LATEX_MACRO_SPLIT.split(sentence)
        ]
        lines = []
        indentation = 0
        for sentence in sentences:
            words = [
                re.sub(r"\s+", " ", word) for word in WORD.findall(sentence)
            ]
            boundaries = _math_boundaries(words)
            if filetype == "latex":
                indentation = 0
            offset = 0
            while words:
                upto = _next_break(
                    words, wrapnumber, punctuation_slop, boundaries, offset
                )
                lines.append(" " * indentation + " ".join(words[: upto + 1]))
                words = words[upto + 1 :]
                offset += upto + 1
                if indentation == 0:
                    indentation = indent_amount
        output.append(leading + "\n".join(lines) + trailing)
    return "".join(output)


def _prepare(filename, cleanoo=False, i=-1):
    """Load text, detect filetype, resolve indentation, strip OO cruft.

    Shared preamble for wr and wrchk. Returns
    (alltext, filetype, indent_amount, display_name), where display_name
    is "<stdin>" when reading stdin and filename otherwise.
    """
    indent_amount = i if i != -1 else 4
    # {{{ load the file
    if filename == "-":
        sys.stdin.reconfigure(encoding="utf-8")
        alltext = sys.stdin.read()
        filetype = "latex"
        display_name = "<stdin>"
    else:
        with open(filename, encoding="utf-8") as fp:
            alltext = fp.read()
        # {{{ determine if the filetype is latex or markdown
        file_extension = filename.split(".")[-1]
        if file_extension == "tex":
            filetype = "latex"
        elif file_extension in ("md", "qmd"):
            filetype = "markdown"
        if filetype == "markdown" and i == -1:
            indent_amount = 0
        # }}}
        display_name = filename
    # }}}
    # {{{ strip stupid commands that appear in openoffice conversion
    if cleanoo:
        alltext = re.sub(r"\\bigskip\b\s*", "", alltext)
        alltext = re.sub(r"\\;", "", alltext)
        alltext = re.sub(r"(?:\\ ){4}", r"\quad ", alltext)
        alltext = re.sub(r"\\ ", " ", alltext)
        # alltext = re.sub('\\\\\n',' ',alltext)
        # {{{ remove select language an accompanying bracket
        m = re.search(r"{\\selectlanguage{english}", alltext)
        while m:
            stop_bracket = match_paren(alltext, m.start(), "{")
            alltext = (
                alltext[: m.start()]
                + alltext[m.end() : stop_bracket]
                + alltext[stop_bracket + 1 :]
            )  # pos is the position of
            #                         the matching curly bracket
            m = re.search(r"{\\selectlanguage{english}", alltext)
        # }}}
        # {{{ remove the remaining select languages
        m = re.search(r"\\selectlanguage{english}", alltext)
        while m:
            alltext = alltext[: m.start()] + alltext[m.end() :]
            m = re.search(r"\\selectlanguage{english}", alltext)
        # }}}
        # {{{ remove mathit
        m = re.search(r"\\mathit{", alltext)
        while m:
            # print("-------------")
            # print(alltext[m.start() : m.end()])
            # print("-------------")
            stop_bracket = match_paren(alltext, m.end() - 1, "{")
            alltext = (
                alltext[: m.start()]
                + alltext[m.end() : stop_bracket]
                + alltext[stop_bracket + 1 :]
            )  # pos is the position of
            #                         the matching curly bracket
            m = re.search(r"\\mathit{", alltext)
        # }}}
    # }}}
    return alltext, filetype, indent_amount, display_name


@register_command(
    "wrap with indented sentence format (for markdown or latex).",
    "wrap with indented sentence format (for markdown or latex).\n"
    "Optional flag --cleanoo cleans latex exported from\n"
    "OpenOffice/LibreOffice\n"
    "Optional flag -i # specifies indentation level for subsequent\n"
    "lines of a sentence (defaults to 4 -- e.g. for markdown you\n"
    "will always want -i 0)",
    help={
        "filename": "Input file to wrap. Use '-' to read from stdin.",
        "cleanoo": "Strip LibreOffice markup before wrapping.",
        "i": "Indentation level for wrapped lines.",
    },
    argument_options={
        **WRAPPING_ARGUMENTS,
        "punctuation_slop": WRAPPING_ARGUMENTS["trailing_dependent_phrase"],
    },
    filename_extensions={"filename": [".md", ".tex"]},
)
def wr(
    filename, wrapnumber=45,
    punctuation_slop=DEFAULT_TRAILING_DEPENDENT_PHRASE, cleanoo=False, i=-1,
):
    alltext, filetype, indent_amount, _ = _prepare(filename, cleanoo, i)
    if filetype == "markdown":
        # reattach detached pandoc-crossref markers before wrapping
        alltext = DETACHED_CROSSREF.sub(
            lambda found: (
                re.sub(r"\s+", " ", found["marker"])
                if found["marker"]
                else found[0][: len(found[0]) - len(found["gap"])]
            ),
            alltext,
        )
        result = wrap_blocks(
            markdown_blocks(alltext),
            wrapnumber,
            punctuation_slop,
            indent_amount,
        )
    else:
        classified = classify_lines(alltext, filetype, normalize_math=True)
        lines = []
        for wrappable, group in itertools.groupby(
            classified, key=lambda x: x[0]
        ):
            content = "".join(line for _, line in group)
            lines.append(
                wrap_prose(
                    content,
                    wrapnumber,
                    punctuation_slop,
                    filetype,
                    indent_amount,
                )
                if wrappable
                else content
            )
        result = "".join(lines)
    if filename == "-":
        sys.stdout.write(result)
    else:
        with open(filename, "w", encoding="utf-8") as fp:
            fp.write(result)


def check_prose(content, wrapnumber, punctuation_slop, line_start=1):
    """Report source lines in `content` that break wr's rules.

    Checks mirror wrap_prose's own paragraph/sentence/macro
    splitting so the two commands never disagree about what counts as a
    sentence: lines must not hold more words than wr's own greedy choice
    would put there (see the fragment check below), and a sentence must not end
    in the middle of a source line. A sentence-ending period followed by
    a backslash-space (`\\ `) rather than a plain space -- the standard
    LaTeX/Pandoc way to mark an abbreviation -- is never mistaken for a
    boundary in the first place, since SENTENCE_BOUNDARY requires the
    character right after the punctuation to be a plain space or
    newline; no extra escape handling is needed for that case.
    """
    issues = []
    line = line_start
    for paragraph in PARAGRAPH_SPLIT.split(content):
        if not paragraph.strip():
            line += paragraph.count("\n")
            continue
        stripped = paragraph.strip("\n")
        leading_newlines = len(paragraph) - len(paragraph.lstrip("\n"))
        para_line = line + leading_newlines
        parts = SENTENCE_BOUNDARY.split(stripped)
        sentences, separators = [], []
        for j in range(0, len(parts), 3):
            if j + 2 < len(parts):
                sentences.append(parts[j] + parts[j + 1])
                separators.append(parts[j + 2])
            else:
                sentences.append(parts[j])
        offset = 0
        for k, sentence in enumerate(sentences):
            sentence_start = offset
            frag_offset = sentence_start
            for fragment in LATEX_MACRO_SPLIT.split(sentence):
                if fragment:
                    # {{{ check line lengths within this sentence fragment
                    words, positions = [], []
                    for match in WORD.finditer(fragment):
                        words.append(match.group())
                        positions.append(frag_offset + match.start())
                    if words:
                        ends = positions[1:] + [frag_offset + len(fragment)]
                        breaks_after = [
                            "\n"
                            in stripped[
                                positions[j] + len(words[j]) : ends[j]
                            ]
                            for j in range(len(words))
                        ]
                        boundaries = _math_boundaries(words)
                        fragment_offset = 0
                        while fragment_offset < len(words):
                            upto = _next_break(
                                words[fragment_offset:],
                                wrapnumber,
                                punctuation_slop,
                                boundaries,
                                fragment_offset,
                            )
                            wr_end = fragment_offset + upto
                            actual_end = fragment_offset
                            while (
                                actual_end < len(words) - 1
                                and not breaks_after[actual_end]
                            ):
                                actual_end += 1
                            line_length = (
                                positions[actual_end]
                                + len(words[actual_end])
                                - positions[fragment_offset]
                            )
                            if actual_end > wr_end:
                                overflow = words[wr_end + 1]
                                rule = (
                                    "line too long"
                                    if line_length > wrapnumber
                                    else "trailing dependent phrase"
                                )
                                issue_line = para_line + stripped.count(
                                    "\n", 0, positions[actual_end]
                                )
                                column = (
                                    positions[wr_end + 1] - stripped.rfind(
                                        "\n", 0, positions[wr_end + 1]
                                    )
                                )
                                issues.append(
                                    (
                                        issue_line,
                                        f"{rule}: wr would break after "
                                        f"'{words[wr_end]}' (before "
                                        f"'{overflow}'); move '{overflow}' "
                                        "onward to the next line, or shorten "
                                        f"this sentence [column {column}]",
                                    )
                                )
                            fragment_offset = actual_end + 1
                    # }}}
                frag_offset += len(fragment)
            offset += len(sentence)
            if k < len(separators):
                sep = separators[k]
                offset += len(sep)
                if sep == " " and (
                    k + 1 >= len(sentences) or sentences[k + 1].strip()
                ):
                    issue_line = para_line + stripped.count(
                        "\n", 0, sentence_start + len(sentence) - 1
                    )
                    issues.append(
                        (
                            issue_line,
                            "sentence ends mid-line here; add a line break "
                            "after the sentence, or write a backslash-"
                            r"space (\ ) instead of a plain space if this "
                            "is an abbreviation, not a sentence end",
                        )
                    )
        line += paragraph.count("\n")
    return sorted(issues)


def _iter_classified_spans(text, filetype, line_start=1):
    """Yield (line_number, content) for each wrappable classify_lines run.

    Shared by wrchk's latex path and by _iter_block_spans for markdown's
    leaf prose blocks -- both just need the same protected-region
    exclusions wr itself uses.
    """
    # normalizing math can add lines (e.g. splitting "$${#eq:x}"), which
    # would shift every reported line number after it
    classified = classify_lines(text, filetype)
    line = line_start
    for wrappable, group in itertools.groupby(classified, key=lambda x: x[0]):
        content = "".join(l for _, l in group)
        if wrappable:
            yield line, content
        line += content.count("\n")


def _iter_block_spans(blocks, wrapnumber, line_start=1):
    """Yield (line_number, width, content) for markdown's wrappable prose.

    Mirrors wrap_blocks' recursion (reduce width by a container's margin,
    recurse into children, classify_lines on leaf text) but yields spans
    to check instead of wrapping them.
    """
    line = line_start
    for block in blocks:
        span = block.text.count("\n")
        if block.kind == "raw":
            pass
        elif block.children:
            yield from _iter_block_spans(
                block.children, max(1, wrapnumber - block.margin), line
            )
        else:
            for sub_line, content in _iter_classified_spans(
                block.text, "markdown", line
            ):
                yield sub_line, wrapnumber, content
        line += span


# also used by: line_alignment.align_line_breaks for comment-aware alignment.
def _html_comment_spans(content, initially_open=False):
    """Find comment offsets, excluding literal delimiters in code or math."""
    spans = []
    start = 0 if initially_open else None
    fence = None
    inline_code = None
    math = None
    offset = 0
    tokens = re.compile(r"<!--|-->|`+|(?<!\\)\$\$|(?<!\\)\$")
    for line in content.splitlines(keepends=True):
        opening = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if start is None and inline_code is None and math is None:
            if fence is not None:
                if (
                    opening and opening[1][0] == fence[0]
                    and len(opening[1]) >= len(fence)
                ):
                    fence = None
                offset += len(line)
                continue
            if opening:
                fence = opening[1]
                offset += len(line)
                continue
        for token in tokens.finditer(line):
            value = token[0]
            if start is not None:
                if value == "-->":
                    spans.append((start, offset + token.end()))
                    start = None
            elif inline_code is not None:
                if value == inline_code:
                    inline_code = None
            elif math is not None:
                if value == math:
                    math = None
            elif value.startswith("`"):
                inline_code = value
            elif value in ("$", "$$"):
                math = value
            elif value == "<!--":
                start = offset + token.start()
        offset += len(line)
    if start is not None:
        spans.append((start, len(content)))
    return spans


# also used by: line_alignment.align_line_breaks, which masks complete hunks.
def _mask_html_comments(content, initially_open=False):
    """Hide comment characters while preserving offsets and line endings."""
    masked = list(content)
    for start, stop in _html_comment_spans(content, initially_open):
        masked[start:stop] = [
            char if char in "\r\n" else " " for char in content[start:stop]
        ]
    return "".join(masked)


def markdown_lint_issues_from_text(
    content, wrapnumber=45, punctuation_slop=20
):
    """Return Markdown writing issues, including unfinished source spans."""
    masked_content = _mask_html_comments(content)
    comment_spans = _html_comment_spans(content)
    masked_lines = masked_content.splitlines()
    prose_content = masked_content
    # trailing spaces are reported separately below, and a double space
    # (a hard line break) must not look like a sentence ending mid-line
    prose_content = re.sub(r"[ \t]+$", "", prose_content, flags=re.M)
    issues = [
        issue
        for line, width, span in _iter_block_spans(
            markdown_blocks(prose_content), wrapnumber
        )
        for issue in check_prose(span, width, punctuation_slop, line)
    ]
    issues.extend(
        (issue["line"], issue["message"])
        for issue in unclosed_markdown_spans(content)
    )
    # {{{ report single trailing spaces, misspelled comment tags and
    # detached crossref markers
    fence = None
    offset = 0
    for number, raw_line in enumerate(content.splitlines(keepends=True), 1):
        line = raw_line.rstrip("\r\n")
        last_character = offset + len(line) - 1
        offset += len(raw_line)
        opening = re.match(r"[ \t]*(\x60{3,}|~{3,})", line)
        if opening and (fence is None or opening[1].startswith(fence)):
            fence = None if fence else opening[1]
            continue
        if fence is not None:
            continue
        if re.search(r"(?<! ) $", line) and not any(
            start <= last_character < stop for start, stop in comment_spans
        ):
            issues.append((
                number,
                "trailing space: remove the single space at the end of this "
                "line (two spaces are a deliberate hard line break)",
            ))
        misspelled = MISSPELLED_COMMENT_TAG.search(masked_lines[number - 1])
        if misspelled:
            issues.append((
                number,
                f"misspelled comment tag: {misspelled[0]} should be "
                f"<{misspelled[1]}{misspelled[2]}com{misspelled[3] or ''}>",
            ))
    for found in DETACHED_CROSSREF.finditer(prose_content):
        if found["gap"] == "":
            continue
        issues.append((
            prose_content.count("\n", 0, found.start()) + 1,
            "detached crossref marker: keep the {#eq:...} or {#fig:...} "
            "marker on one line, directly after the closing $$ or )",
        ))
    # }}}
    return sorted(issues)


def unclosed_markdown_spans(content, math_line_limit=50):
    """Find unfinished math and HTML comments in Markdown source."""
    lines = content.splitlines(keepends=True)
    spans = []
    fence_char = None
    fence_size = 0
    math_start = None
    math_delimiter = None
    math_content = []
    comment_start = None
    comment_content = []
    inline_code_delimiter = None
    token_pattern = re.compile(
        r"<!--|-->|(?<!\\)\$\$|(?<!\\)\$|`+"
    )

    for line_number, line in enumerate(lines, 1):
        fence = re.match(r"^[ \t]*(?P<marker>`{3,}|~{3,})", line)
        if fence_char is not None:
            if (
                fence
                and fence.group("marker")[0] == fence_char
                and len(fence.group("marker")) >= fence_size
            ):
                fence_char = None
            continue
        if fence:
            fence_char = fence.group("marker")[0]
            fence_size = len(fence.group("marker"))
            continue

        for token in token_pattern.finditer(line):
            value = token.group()
            if comment_start is not None:
                if value == "-->":
                    comment_start = None
                    comment_content = []
                continue
            if math_start is not None:
                if value == math_delimiter:
                    math_start = None
                    math_delimiter = None
                    math_content = []
                continue
            if inline_code_delimiter is not None:
                if value.startswith("`") and value == inline_code_delimiter:
                    inline_code_delimiter = None
                continue
            if value.startswith("`"):
                inline_code_delimiter = value
                continue
            if value == "<!--":
                comment_start = line_number
                comment_content = [line[token.start() :]]
            elif value in {"$", "$$"}:
                math_start = line_number
                math_delimiter = value
                math_content = [line[token.start() :]]
        if comment_start is not None and line_number > comment_start:
            comment_content.append(line)
        if math_start is not None and line_number > math_start:
            math_content.append(line)

    if comment_start is not None:
        spans.append(
            {
                "kind": "comment",
                "line": comment_start,
                "message": "unclosed HTML comment: add '-->' to close it",
                "offending": "".join(comment_content).rstrip("\r\n"),
            }
        )
    if (
        math_start is not None
        and len(lines) - math_start + 1 >= math_line_limit
    ):
        spans.append(
            {
                "kind": "math",
                "line": math_start,
                "message": (
                    "unclosed math: add the matching "
                    f"'{math_delimiter}' to close it"
                ),
                "offending": "".join(math_content).rstrip("\r\n"),
                "delimiter": math_delimiter,
            }
        )
    return spans


# Kept public so the automatic source edits can be unit-tested directly.
def apply_markdown_issue_fix(content, line_number, message):
    """Insert one source line break for a wrchk Markdown issue."""
    lines = content.splitlines(keepends=True)
    index = line_number - 1
    if index < 0 or index >= len(lines):
        raise ValueError(
            f"Markdown issue refers to missing line {line_number}"
        )
    if message.startswith("detached crossref marker"):
        # {{{ join the marker onto its "$$" or ")" (this can remove a line)
        start = sum(len(line) for line in lines[:index])
        found = next(
            found
            for found in DETACHED_CROSSREF.finditer(content, start)
            if found["gap"] != ""
        )
        if found["gap"] is None:
            span = found.span("marker")
            joined = re.sub(r"\s+", " ", found["marker"])
        else:
            span = found.span("gap")
            joined = ""
        updated = content[: span[0]] + joined + content[span[1] :]
        # report the whole source lines around the join
        line_start = content.rfind("\n", 0, found.start()) + 1
        line_end = content.find("\n", max(found.end(), span[1]))
        if line_end == -1:
            line_end = len(content)
        before = content[line_start:line_end]
        after = updated[
            line_start : line_end - (span[1] - span[0]) + len(joined)
        ]
        return (
            updated,
            before,
            after,
            "One or more crossref markers were separated from their "
            "equation or figure. I joined them back on.",
        )
        # }}}
    old_line = lines[index]
    ending = ""
    if old_line.endswith("\r\n"):
        old_line, ending = old_line[:-2], "\r\n"
    elif old_line.endswith(("\n", "\r")):
        old_line, ending = old_line[:-1], old_line[-1:]
    if not ending:
        ending = "\n"

    # {{{ keep continuation lines inside their Markdown container
    container = re.match(
        r"^((?:[ \t]*>[ \t]?)*)(?:([-+*]|[0-9]+[.)])([ \t]+))?",
        old_line,
    )
    quote_prefix, marker, marker_space = container.groups()
    if marker:
        prefix = quote_prefix + " " * (len(marker) + len(marker_space))
    elif quote_prefix:
        prefix = quote_prefix
    else:
        prefix = re.match(r"^[ \t]*", old_line).group()
    # }}}
    if message.startswith("misspelled comment tag:"):
        fixed = MISSPELLED_COMMENT_TAG.sub(
            lambda found: f"<{found[1]}{found[2]}com{found[3] or ''}>",
            old_line,
        )
        lines[index] = fixed + ending
        return (
            "".join(lines),
            old_line,
            fixed,
            "One or more comment tags were misspelled, so they would not "
            "show as comments. A comment tag is two initials and com, as in "
            "&lt;JFcom&gt;. I corrected them.",
        )
    if message.startswith("trailing space:"):
        lines[index] = old_line[:-1] + ending
        return (
            "".join(lines),
            old_line,
            old_line[:-1],
            "One or more lines ended with a single stray space. I removed "
            "those spaces.",
        )
    if message.startswith(("line too long:", "trailing dependent phrase:")):
        match = re.search(r"after '(.+?)' \(before '(.+?)'\); move", message)
        if match is None:
            raise ValueError(
                f"Cannot find the suggested word in {message!r}"
            )
        # split at the suggested word that follows wr's break word, since the
        # same word can appear earlier on the line (e.g. "for ... ($3x$ for")
        position = re.search(
            r"(?<!\S)" + re.escape(match.group(1)) + r"[ \t]+("
            + re.escape(match.group(2)) + r")(?!\S)",
            old_line,
        )
        if position is None:
            raise ValueError(
                f"Cannot find {match.group(2)!r} after {match.group(1)!r} on "
                f"Markdown line {line_number}"
            )
        column = re.search(r"\[column (\d+)\]$", message)
        split_at = int(column[1]) - 1 if column else position.start(1)
        first = old_line[:split_at].rstrip()
        second = old_line[split_at:].lstrip(" \t")
        reason = (
            "One or more lines carry a short dependent phrase after "
            "punctuation near the maximum width. I moved those phrases "
            "onto new lines."
            if message.startswith("trailing dependent phrase:") else
            "One or more lines were run-on lines, longer than the line "
            "width. I moved the extra words onto new lines."
        )
    elif message.startswith("sentence ends mid-line"):
        boundary = SENTENCE_BOUNDARY.search(
            _mask_html_comments(content).splitlines()[index]
        )
        if boundary is None or boundary.group(2) != " ":
            raise ValueError(
                "Cannot find the sentence break on Markdown line "
                f"{line_number}"
            )
        first = old_line[: boundary.end(1)].rstrip()
        second = old_line[boundary.end(2) :].lstrip(" \t")
        reason = (
            "One or more sentences started in the middle of a source line. "
            "Since you can line-break the source wherever you want (only "
            "double breaks give a new paragraph), you should <b>always "
            "start sentences on new lines</b>. I started each one on a new "
            "line."
        )
    else:
        raise ValueError(f"No automatic fix is available for {message!r}")

    if not first.strip() or not second.strip():
        # a break here would insert a blank line, i.e. a paragraph break
        raise ValueError(
            f"Automatic fix would leave an empty line at {line_number}"
        )
    lines[index] = first + ending + prefix + second + ending
    after = first + "\n" + prefix + second
    return "".join(lines), old_line, after, reason


def autofix_markdown_file(
    filename, wrapnumber=55, punctuation_slop=20, git_head=False,
    git_ref=None, git_index=False,
):
    """Apply safe source line breaks and report unfinished source spans.

    With `git_index` or `git_head`, use the index or HEAD as the baseline.
    An explicit `git_ref` enables alignment and overrides both flags.
    All line-break alignments are applied automatically to keep the diff
    small while enforcing the source wrapping rules.
    """
    with open(filename, encoding="utf-8", newline="") as fp:
        content = fp.read()
    fixes = []
    baseline = None
    if git_ref is not None or git_index or git_head:
        # {{{ read the chosen Git baseline before making source fixes
        directory, basename = os.path.split(os.path.abspath(filename))
        revision = git_ref if git_ref is not None else (
            "" if git_index else "HEAD"
        )
        baseline_label = "Git index" if revision == "" else f"git {revision}"
        baseline_error = (
            f"Cannot read diff-lint baseline {git_ref!r} for {filename}. "
            "Check that the ref exists and contains this file."
        )
        if git_ref == "":
            raise RuntimeError(baseline_error)
        try:
            with subprocess.Popen(
                ["git", "-C", directory, "show", "--end-of-options",
                 revision + ":./" + basename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as shown:
                output, stderr = shown.communicate()
            if shown.returncode == 0:
                baseline = output.decode("utf-8")
            elif git_ref is not None:
                raise RuntimeError(
                    baseline_error + "\n" + stderr.decode("utf-8", "replace")
                )
        except (OSError, UnicodeDecodeError) as exc:
            if git_ref is not None:
                raise RuntimeError(baseline_error + f"\n{exc}") from exc
        # }}}
    if baseline is not None:
        from .line_alignment import align_line_breaks

        # {{{ apply all shared alignments and report the changes made
        results = align_line_breaks(
            baseline, content, width=wrapnumber,
            punctuation_slop=punctuation_slop,
        )
        shift = 0
        updates = []
        for result in results:
            line = result["line"] + shift
            moves = result["moves"]
            chosen = result["aligned"]
            if chosen != result["before"]:
                reasons = []
                if not moves and result["linted"] != result["before"]:
                    reasons.append(
                        "One or more lines broke the source wrapping rules. "
                        "I moved trailing phrases or extra words to new "
                        "lines and started sentences on new lines."
                    )
                if moves:
                    reasons.append(
                        "One or more edits moved line breaks away from "
                        f"where {baseline_label} has them. "
                        "I put those breaks back to minimize the diff, "
                        "while enforcing the source wrapping rules."
                    )
                fixes.append({
                    "line": line, "reason": " ".join(reasons),
                    "before": result["before"].rstrip("\r\n"),
                    "after": chosen.rstrip("\r\n"),
                })
            updates.append((result["start"], result["stop"], chosen))
            shift += chosen.count("\n") - result["before"].count("\n")
        for start, stop, chosen in reversed(updates):
            content = content[:start] + chosen + content[stop:]
        # }}}
    # Lint once, fix every flagged line, then lint again, since fixing one
    # issue at a time re-lints the whole file for every single fix.
    for _ in range(100):
        issues = markdown_lint_issues_from_text(
            content, wrapnumber=wrapnumber, punctuation_slop=punctuation_slop
        )
        fixable = {}
        for line_number, message in issues:
            if not message.startswith(
                ("unclosed math:", "unclosed HTML comment:")
            ):
                # a fix only rewrites its own line, so fix one issue per line
                # per pass and let the next lint catch whatever remains
                fixable.setdefault(line_number, message)
        if not fixable:
            break
        # work from the bottom up so each inserted line break leaves the
        # line numbers of the remaining issues unchanged
        pass_fixes = []
        for line_number in sorted(fixable, reverse=True):
            updated, before, after, reason = apply_markdown_issue_fix(
                content, line_number, fixable[line_number]
            )
            if updated == content:
                raise RuntimeError(
                    "Automatic Markdown fix made no change at line "
                    f"{line_number}"
                )
            pass_fixes.append(
                {
                    "line": line_number,
                    "reason": reason,
                    "before": before,
                    "after": after,
                }
            )
            content = updated
        fixes.extend(reversed(pass_fixes))
    else:
        raise RuntimeError("Too many automatic Markdown fixes were needed.")

    if fixes:
        with open(filename, "w", encoding="utf-8", newline="") as fp:
            fp.write(content)
    return {
        "fixes": fixes,
        "warnings": unclosed_markdown_spans(content),
        "layout": [],
    }


@register_command(
    "check wrapping and sentence-break rules (for markdown or latex).",
    "check that a file already obeys wr's wrapping rules -- without\n"
    "rewriting anything. Reports a source line as too long if it is\n"
    "longer than --wrapnumber characters (and suggests the break wr would\n"
    "use). A short dependent phrase after punctuation near the maximum\n"
    "width must move to the next line; --trailing-dependent-phrase sets\n"
    "that distance (20 by default, 0 to disable). Also\n"
    "reports a sentence that ends in the middle of a source line\n"
    "instead of at a line break. Prints 'file:line: message' for each\n"
    "violation and exits non-zero if any are found. Takes the same\n"
    "arguments as wr.",
    help={
        "filename": "Input file to check. Use '-' to read from stdin.",
        "cleanoo": "Strip LibreOffice markup before checking.",
        "i": "Accepted for parity with wr; unused by the checks.",
    },
    filename_extensions={"filename": [".md", ".tex"]},
    argument_options={
        **WRAPPING_ARGUMENTS,
        "punctuation_slop": WRAPPING_ARGUMENTS["trailing_dependent_phrase"],
    },
)
def wrchk(
    filename, wrapnumber=45,
    punctuation_slop=DEFAULT_TRAILING_DEPENDENT_PHRASE, cleanoo=False, i=-1,
):
    alltext, filetype, _, display_name = _prepare(filename, cleanoo, i)
    if filetype == "markdown":
        issues = markdown_lint_issues_from_text(
            alltext, wrapnumber, punctuation_slop
        )
    else:
        spans = (
            (line, wrapnumber, content)
            for line, content in _iter_classified_spans(alltext, filetype)
        )
        issues = [
            issue
            for line, width, content in spans
            for issue in check_prose(content, width, punctuation_slop, line)
        ]
    for line, message in issues:
        print(f"{display_name}:{line}: {message}")
    if issues:
        raise SystemExit(1)
