import os
import re
import subprocess
import sys
import itertools
from bisect import bisect_left
from dataclasses import dataclass, field, replace

from .command_registry import register_command
from .wrapping_options import (
    DEFAULT_DESIRED_WIDTH, DEFAULT_TRAILING_DEPENDENT_PHRASE,
    WRAPPING_ARGUMENTS,
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
# Image syntax stays attached when emitting source, but occupies no width
# in the caption. The marked endpoints distinguish it from caption text.
IMAGE_SYNTAX = re.compile(r"\U000f015d[^\U000f0129\U000f017d]*"
                          r"[\U000f0129\U000f017d]")
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
PROSE_FIX_REASONS = {
    "line too long": (
        "One or more lines were run-on lines, longer than the line "
        "width. I moved the extra words onto new lines."
    ),
    "trailing dependent phrase": (
        "One or more lines carry a short dependent phrase after "
        "punctuation near the maximum width. I moved those phrases "
        "onto new lines."
    ),
    "sentence": (
        "One or more sentences started in the middle of a source line. "
        "Since you can line-break the source wherever you want (only "
        "double breaks give a new paragraph), you should <b>always "
        "start sentences on new lines</b>. I started each one on a new "
        "line."
    ),
}


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


def markdown_blocks(text, *, targets=None):
    """Split Markdown containers recursively, keeping original source spans."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    allowed = [
        flag for flag, _ in classify_lines(text, strict=False, targets=targets)
    ]
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


def image_target_spans(text):
    """Locate image destinations and attached attributes in source text."""
    return markdown_syntax(text).image_targets if "![" in text else []


def protect_image_targets(text, restore=False):
    # {{{ Protect image syntax while retaining source offsets.
    # Mark the closing bracket and final delimiter in a separate range so
    # the prose rules can exclude the whole syntax span from the width.
    if restore:
        return "".join(
            chr(ord(c) & 0xFF)
            if 0xF0000 <= ord(c) < 0xF0080
            or c in "\U000f015d\U000f0129\U000f017d"
            else c
            for c in text
        )
    for end, stop in reversed(image_target_spans(text)):
        text = text[:end] + chr(ord(text[end]) + 0xF0100) + "".join(
            chr(ord(c) + 0xF0000) if ord(c) < 128 else c
            for c in text[end + 1:stop - 1]
        ) + chr(ord(text[stop - 1]) + 0xF0100) + text[stop:]
    return text
    # }}}


def classify_lines(
    text,
    filetype="markdown",
    normalize_math=False,
    strict=True,
    *,
    targets=None,
):
    """Return (wrappable, line) pairs with original line endings and text."""
    lines = text.splitlines(keepends=True)
    scan_lines = lines
    if filetype == "markdown":
        # Targets are syntax even when their contents resemble HTML or math.
        targets = image_target_spans(text) if targets is None else targets
        if targets:
            scan_lines = _mask_spans(text, targets, "\0").splitlines(
                keepends=True
            )
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
        # {{{ preserve HTML outside tables and math
        idx = 0
        in_math = False
        while idx < len(lines):
            if not wrappable[idx] and not in_math:
                idx += 1
                continue
            line = scan_lines[idx]
            dollars = list(DISPLAY_MATH.finditer(line))
            match = re.search(r"<(\w+)(?:\s[^>]*)?>", line)
            if in_math or (
                dollars and (not match or dollars[0].start() < match.start())
            ):
                wrappable[idx] = True
                if len(dollars) % 2:
                    in_math = not in_math
            elif match:
                opener = "<" + match[1]
                pos = match.start()
                remaining = "".join(scan_lines[idx:])
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
        zip(wrappable, lines, scan_lines), lambda x: x[0]
    ):
        _, originals, scans = zip(*group)
        content = "".join(originals)
        if not allowed:
            result.extend(
                (False, line) for line in content.splitlines(keepends=True)
            )
            continue
        delimiters = list(DISPLAY_MATH.finditer("".join(scans)))
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
    counts = list(itertools.accumulate(
        len(word) + bool(word) for word in words
    ))
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
            word[-1:] and word[-1] in ",;:)-–—"
            or (j + 1 < len(words) and words[j + 1].startswith("("))
            or offset + j in boundaries
        )
        and j < len(words) - 1
        and words[j + 1]
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
    if filetype == "markdown":
        text = protect_image_targets(text)
    output = []
    # Keep paragraph separators and the boundary newlines next to exclusions.
    paragraphs = PARAGRAPH_SPLIT.split(text)
    if filetype == "markdown":
        # Hard line breaks are source boundaries, not wrappable whitespace.
        paragraphs = [
            part for paragraph in paragraphs
            for part in re.split(r"( {2,}\r?\n)", paragraph)
        ]
    for paragraph in paragraphs:
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
            prose = [IMAGE_SYNTAX.sub("", word) for word in words]
            boundaries = _math_boundaries(prose)
            if filetype == "latex":
                indentation = 0
            offset = 0
            while words:
                upto = _next_break(
                    prose, wrapnumber, punctuation_slop, boundaries, offset
                )
                lines.append(" " * indentation + " ".join(words[: upto + 1]))
                words = words[upto + 1 :]
                prose = prose[upto + 1 :]
                offset += upto + 1
                if indentation == 0:
                    indentation = indent_amount
        output.append(leading + "\n".join(lines) + trailing)
    result = "".join(output)
    return (
        protect_image_targets(result, restore=True)
        if filetype == "markdown" else result
    )


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
        # Reattach markers only where the parser recognizes active source.
        for found in reversed(list(_detached_crossrefs(alltext))):
            group = "marker" if found["marker"] else "gap"
            start, stop = found.span(group)
            replacement = re.sub(r"\s+", " ", found[group]) if (
                group == "marker"
            ) else ""
            alltext = alltext[:start] + replacement + alltext[stop:]
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


@dataclass(frozen=True)
class ProseBreak:
    line: int
    column: int
    kind: str
    message: str


def prose_breaks(
    content, wrapnumber, punctuation_slop, line_start=1, overflow_words=0,
    *, all_breaks=False, editable_rows=None, hard_width_rows=(),
):
    """Report source lines in `content` that break wr's rules.

    Diff alignment can set overflow_words to tolerate that many words ending
    beyond the character width. Ordinary wrapping checks use a strict limit.

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
    content = protect_image_targets(content)
    issues = []
    line = line_start
    for paragraph in PARAGRAPH_SPLIT.split(content):
        if not paragraph.strip():
            line += paragraph.count("\n")
            continue
        stripped = paragraph.strip("\n")
        source = protect_image_targets(stripped, restore=True)
        leading_newlines = len(paragraph) - len(paragraph.lstrip("\n"))
        para_line = line + leading_newlines
        newlines = (
            [match.start() for match in re.finditer("\n", source)]
            if hard_width_rows or editable_rows is not None else []
        )
        if hard_width_rows:
            parts = []
            previous = 0
            for match in SENTENCE_BOUNDARY.finditer(stripped):
                row = para_line - 1 + bisect_left(newlines, match.start(2))
                if match[2] == " " and row in hard_width_rows:
                    continue
                parts.extend((
                    stripped[previous:match.start()], *match.groups(),
                ))
                previous = match.end()
            parts.append(stripped[previous:])
        else:
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
                        prose = [IMAGE_SYNTAX.sub("", word) for word in words]
                        prose_ends = [
                            position + len(word) - removed
                            for position, word, removed in zip(
                                positions, words, itertools.accumulate(
                                    len(raw) - len(caption)
                                    for raw, caption in zip(words, prose)
                                ),
                            )
                        ]
                        boundaries = _math_boundaries(prose)
                        fragment_offset = 0
                        while fragment_offset < len(words):
                            actual_end = fragment_offset
                            while (
                                actual_end < len(words) - 1
                                and not breaks_after[actual_end]
                            ):
                                actual_end += 1
                            line_start_pos = (
                                prose_ends[fragment_offset]
                                - len(prose[fragment_offset])
                            )
                            line_length = (
                                prose_ends[actual_end] - line_start_pos
                            )
                            row = para_line - 1 + bisect_left(
                                newlines, positions[fragment_offset],
                            )
                            hard_width_only = row in hard_width_rows
                            if (
                                hard_width_only and line_length <= wrapnumber
                                or not hard_width_only
                                and editable_rows is not None
                                and row not in editable_rows
                            ):
                                fragment_offset = actual_end + 1
                                continue
                            wr_end = fragment_offset + _next_break(
                                prose[fragment_offset:], wrapnumber,
                                punctuation_slop, boundaries, fragment_offset,
                            )
                            if line_length > wrapnumber:
                                # Source gaps can be wider than the single
                                # spaces assumed by the wrapping heuristic.
                                wr_end = min(wr_end, max(
                                    fragment_offset,
                                    bisect_left(
                                        prose_ends,
                                        line_start_pos + wrapnumber + 1,
                                        fragment_offset, actual_end + 1,
                                    ) - 1,
                                ))
                            # Diff alignment can keep a few extra words to
                            # avoid moving the sentence tail onto a new line.
                            # Count against the character limit, independently
                            # of an earlier preferred punctuation break.
                            excess = sum(
                                prose_ends[j] - line_start_pos > wrapnumber
                                for j in range(fragment_offset, actual_end + 1)
                            )
                            if actual_end > wr_end and not (
                                overflow_words and 0 < excess <= overflow_words
                            ):
                                # A protected image target may span lines.
                                # Report the physical words at the break so
                                # the line-based fixer can find them.
                                split_at = positions[wr_end + 1]
                                overflow = source[
                                    split_at:split_at + len(words[wr_end + 1])
                                ].split("\n", 1)[0].rstrip("\r")
                                preceding = source[
                                    positions[wr_end]:
                                    positions[wr_end] + len(words[wr_end])
                                ].rsplit("\n", 1)[-1]
                                rule = (
                                    "line too long"
                                    if line_length > wrapnumber
                                    else "trailing dependent phrase"
                                )
                                issue_line = para_line + source.count(
                                    "\n", 0, split_at
                                )
                                column = split_at - source.rfind(
                                    "\n", 0, split_at
                                )
                                issues.append(
                                    ProseBreak(
                                        issue_line, column, rule,
                                        f"{rule}: wr would break after "
                                        f"'{preceding}' (before "
                                        f"'{overflow}'); move '{overflow}' "
                                        "onward to the next line, or shorten "
                                        f"this sentence [column {column}]",
                                    )
                                )
                                if all_breaks:
                                    fragment_offset = wr_end + 1
                                    continue
                            fragment_offset = actual_end + 1
                    # }}}
                frag_offset += len(fragment)
            offset += len(sentence)
            if k < len(separators):
                sep = separators[k]
                offset += len(sep)
                if sep == " " and not re.match(
                    r"[ \t]*\r?\n", stripped[offset:]
                ) and (
                    k + 1 >= len(sentences) or sentences[k + 1].strip()
                ):
                    issue_line = para_line + source.count(
                        "\n", 0, sentence_start + len(sentence) - 1
                    )
                    issues.append(
                        ProseBreak(
                            issue_line,
                            offset - source.rfind("\n", 0, offset),
                            "sentence",
                            "sentence ends mid-line here; add a line break "
                            "after the sentence, or write a backslash-"
                            r"space (\ ) instead of a plain space if this "
                            "is an abbreviation, not a sentence end",
                        )
                    )
        line += source.count("\n") + len(paragraph) - len(stripped)
    return issues


def check_prose(
    content, wrapnumber, punctuation_slop, line_start=1, overflow_words=0,
):
    return sorted(
        (edit.line, edit.message) for edit in prose_breaks(
            content, wrapnumber, punctuation_slop, line_start, overflow_words,
        )
    )


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


@dataclass
class MarkdownSyntax:
    comments: list = field(default_factory=list)
    equations: list = field(default_factory=list)
    image_targets: list = field(default_factory=list)
    literal: list = field(default_factory=list)
    unfinished_comment: int | None = None
    unfinished_math: tuple | None = None


def markdown_syntax(content, initially_open=False):
    """Find original source spans before matching, wrapping or reporting."""
    syntax = MarkdownSyntax()
    start = 0 if initially_open else None
    fence = None
    fence_start = None
    inline_code = None
    inline_start = None
    math = None
    math_start = None
    indented_code = False
    previous_blank = True
    offset = 0
    tokens = re.compile(r"<!--|-->|`+|\$\$|\$|!\[")
    for line in content.splitlines(keepends=True):
        opening = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if start is None and inline_code is None and math is None:
            if fence is None:
                indented = line.startswith(("    ", "\t"))
                if indented_code and not indented and line.strip():
                    indented_code = False
                if (previous_blank and indented) or indented_code:
                    indented_code = True
                    syntax.literal.append((offset, offset + len(line)))
                    previous_blank = not line.strip()
                    offset += len(line)
                    continue
            if fence is not None:
                if (
                    opening and opening[1][0] == fence[0]
                    and len(opening[1]) >= len(fence)
                ):
                    fence = None
                    syntax.literal.append((fence_start, offset + len(line)))
                offset += len(line)
                continue
            if opening:
                fence = opening[1]
                fence_start = offset
                offset += len(line)
                continue
        for token in tokens.finditer(line):
            value = token[0]
            position = offset + token.start()
            if (
                syntax.image_targets and position < syntax.image_targets[-1][1]
                and any(a <= position < b for a, b in syntax.image_targets)
            ):
                continue
            if value in ("$", "$$", "!["):
                preceding = line[:token.start()]
                if (len(preceding) - len(preceding.rstrip("\\"))) % 2:
                    continue
            if start is not None:
                if value == "-->":
                    syntax.comments.append((start, offset + token.end()))
                    start = None
            elif inline_code is not None:
                if value == inline_code:
                    inline_code = None
                    syntax.literal.append((inline_start, offset + token.end()))
            elif math is not None:
                if value == math:
                    syntax.equations.append((math_start, offset + token.end()))
                    math = None
            elif value.startswith("`"):
                inline_code = value
                inline_start = position
            elif value in ("$", "$$"):
                math = value
                math_start = offset + token.start()
            elif value == "<!--":
                start = offset + token.start()
            elif value == "![":
                try:
                    end = match_paren(content, position + 1, "[") + 1
                    if content[end:end + 1] != "(":
                        continue
                    stop = match_paren(content, end, "(") + 1
                    if content[stop:stop + 1] == "{":
                        stop = match_paren(content, stop, "{") + 1
                except RuntimeError:
                    continue
                syntax.image_targets.append((end - 1, stop))
                syntax.image_targets.sort()
        offset += len(line)
        previous_blank = not line.strip()
    if start is not None:
        syntax.comments.append((start, len(content)))
        syntax.unfinished_comment = start
    if math is not None:
        syntax.unfinished_math = (math_start, math)
    if fence is not None:
        syntax.literal.append((fence_start, len(content)))
    return syntax


def _mask_spans(text, spans, fill=" "):
    if not spans:
        return text
    masked = list(text)
    for begin, end in spans:
        masked[begin:end] = [
            char if char in "\r\n" else fill for char in text[begin:end]
        ]
    return "".join(masked)


def _detached_crossrefs(content, syntax=None, start=0):
    syntax = markdown_syntax(content) if syntax is None else syntax
    excluded = sorted(syntax.literal + syntax.comments)
    index = 0
    for found in DETACHED_CROSSREF.finditer(content, start):
        while index < len(excluded) and excluded[index][1] <= found.start():
            index += 1
        if found["gap"] != "" and (
            index == len(excluded) or found.end() <= excluded[index][0]
        ):
            yield found


# also used by: line_alignment.align_line_breaks and word_merge.tokenize.
def structural_rows(text, filetype, syntax=None):
    """Comments, math, the text with both blanked out, and which rows are
    rewrappable prose.

    Comments and math are blanked (keeping their line breaks), so that
    their contents cannot make classify_lines protect a row.
    """
    syntax = markdown_syntax(text) if syntax is None else syntax
    comments, equations = syntax.comments, syntax.equations
    structural = _mask_spans(text, comments + equations)
    allowed = [
        flag and bool(line.strip())
        for (flag, _), line in zip(
            classify_lines(
                structural, filetype, strict=False,
                targets=syntax.image_targets,
            ),
            text.splitlines(keepends=True),
        )
    ]
    return comments, equations, structural, allowed


# also used by: line_alignment.align_line_breaks for comment-aware alignment.
def _html_comment_spans(content, initially_open=False):
    """Find comment offsets, excluding literal delimiters in code or math."""
    return markdown_syntax(content, initially_open).comments


# also used by: line_alignment.align_line_breaks, which masks complete hunks.
def _mask_html_comments(content, initially_open=False):
    """Hide comment characters while preserving offsets and line endings."""
    return _mask_spans(content, _html_comment_spans(content, initially_open))


def markdown_prose_spans(masked_content, wrapnumber):
    """Yield prose with its source line and available container width."""
    # trailing spaces are reported separately below, and a double space
    # (a hard line break) must not look like a sentence ending mid-line
    return _iter_block_spans(
        markdown_blocks(re.sub(r"[ \t]+$", "", masked_content, flags=re.M)),
        wrapnumber,
    )


def markdown_wrap_edits(
    content, wrapnumber, punctuation_slop, editable_rows, hard_width_rows,
    *, syntax=None,
):
    """Plan replacements of source lines using parsed Markdown and offsets.

    Row indices are zero based. Edited prose uses the usual sentence and
    clause rules; other selected rows are subject only to the hard width.
    """
    syntax = markdown_syntax(content) if syntax is None else syntax
    masked = _mask_spans(content, syntax.comments)
    source_rows = content.splitlines(keepends=True)
    masked_rows = masked.splitlines(keepends=True)
    plan = {}
    # {{{ Map breaks in container bodies back to their original source rows.
    for line, width, span in markdown_prose_spans(masked, wrapnumber):
        rows = span.splitlines(keepends=True)
        block_rows = range(line - 1, line - 1 + len(rows))
        if not any(
            row in editable_rows or row in hard_width_rows
            and len(rows[row - line + 1].rstrip()) > width
            for row in block_rows
        ):
            continue
        for edit in prose_breaks(
            span, width, punctuation_slop, line, all_breaks=True,
            editable_rows=editable_rows, hard_width_rows=hard_width_rows,
        ):
            row = edit.line - 1
            if row not in editable_rows and row not in hard_width_rows:
                continue
            prefix_width = (
                len(masked_rows[row].rstrip())
                - len(rows[row - line + 1].rstrip())
            )
            edit = replace(edit, column=edit.column + prefix_width)
            plan.setdefault(row, {})[edit.column] = edit
    # }}}
    for row, edits in plan.items():
        original = source_rows[row].rstrip("\r\n")
        ending = source_rows[row][len(original):]
        columns = [0, *(column - 1 for column in sorted(edits)), len(original)]
        parts = [original[a:b] for a, b in zip(columns, columns[1:])]
        if all(part.strip() for part in parts):
            prefix = _continuation_prefix(original)
            yield row, ((ending or "\n") + prefix).join(
                part.lstrip() if index else part
                for index, part in enumerate(
                    [part.rstrip() for part in parts[:-1]] + parts[-1:]
                )
            ) + ending, min(edits.values(), key=lambda edit: edit.column).kind


def markdown_lint_issues_from_text(
    content, wrapnumber=45, punctuation_slop=20, overflow_words=0,
    *, check_wrapping=True, syntax=None,
):
    """Return Markdown writing issues, including unfinished source spans."""
    syntax = markdown_syntax(content) if syntax is None else syntax
    issues = [
        issue
        for line, width, span in markdown_prose_spans(
            _mask_spans(content, syntax.comments), wrapnumber,
        )
        for issue in check_prose(
            span, width, punctuation_slop, line, overflow_words,
        )
    ] if check_wrapping else []
    issues.extend(
        (issue["line"], issue["message"])
        for issue in unclosed_markdown_spans(content, syntax=syntax)
    )
    # {{{ report single trailing spaces, misspelled comment tags and
    # detached crossref markers
    offset = 0
    protected = syntax.comments + syntax.image_targets + syntax.literal
    tag_lines = _mask_spans(content, protected).splitlines()
    for number, raw_line in enumerate(content.splitlines(keepends=True), 1):
        line = raw_line.rstrip("\r\n")
        last_character = offset + len(line) - 1
        offset += len(raw_line)
        if re.search(r"(?<! ) $", line) and not any(
            start <= last_character < stop for start, stop in protected
        ):
            issues.append((
                number,
                "trailing space: remove the single space at the end of this "
                "line (two spaces are a deliberate hard line break)",
            ))
        misspelled = MISSPELLED_COMMENT_TAG.search(tag_lines[number - 1])
        if misspelled:
            issues.append((
                number,
                f"misspelled comment tag: {misspelled[0]} should be "
                f"<{misspelled[1]}{misspelled[2]}com{misspelled[3] or ''}>",
            ))
    for found in _detached_crossrefs(content, syntax):
        issues.append((
            content.count("\n", 0, found.start()) + 1,
            "detached crossref marker: keep the {#eq:...} or {#fig:...} "
            "marker on one line, directly after the closing $$ or )",
        ))
    # }}}
    return sorted(issues)


def unclosed_markdown_spans(content, math_line_limit=50, *, syntax=None):
    """Report unfinished constructs from the shared syntax scan."""
    syntax = markdown_syntax(content) if syntax is None else syntax
    spans = []
    if syntax.unfinished_comment is not None:
        start = syntax.unfinished_comment
        spans.append({
            "kind": "comment",
            "line": content.count("\n", 0, start) + 1,
            "message": "unclosed HTML comment: add '-->' to close it",
            "offending": content[start:].rstrip("\r\n"),
        })
    if syntax.unfinished_math is not None:
        start, delimiter = syntax.unfinished_math
        if len(content[start:].splitlines()) >= math_line_limit:
            spans.append({
                "kind": "math",
                "line": content.count("\n", 0, start) + 1,
                "message": (
                    "unclosed math: add the matching "
                    f"'{delimiter}' to close it"
                ),
                "offending": content[start:].rstrip("\r\n"),
                "delimiter": delimiter,
            })
    return spans


def _continuation_prefix(line):
    container = re.match(
        r"^((?:[ \t]*>[ \t]?)*)(?:(:|[-+*]|[0-9]+[.)])([ \t]+))?",
        line,
    )
    quote, marker, space = container.groups()
    if marker:
        return quote + " " * max(
            4 if marker == ":" else 1, len((marker + space).expandtabs(4)),
        )
    return quote or re.match(r"^[ \t]*", line)[0]


# Kept public so the automatic source edits can be unit-tested directly.
# also used by: line_alignment.py, when linting changed hunks.
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
        found = next(_detached_crossrefs(content, start=start))
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

    prefix = _continuation_prefix(old_line)
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
        if not old_line.startswith(match.group(2), split_at):
            split_at = position.start(1)
        first = old_line[:split_at].rstrip()
        second = old_line[split_at:].lstrip(" \t")
        reason = PROSE_FIX_REASONS[message.split(":", 1)[0]]
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
        reason = PROSE_FIX_REASONS["sentence"]
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


# also used by: tests/test_wrap_check.py and tests/test_line_alignment.py.
def autofix_markdown_file(
    filename, wrapnumber=55, punctuation_slop=20, git_head=False,
    git_ref=None, git_index=False, desired_width=DEFAULT_DESIRED_WIDTH,
):
    """Apply safe source line breaks and report unfinished source spans.

    With `git_index` or `git_head`, use the index or HEAD as the baseline.
    An explicit `git_ref` enables alignment and overrides both flags.
    All line-break alignments are applied automatically to keep the diff
    small while enforcing the source wrapping rules.
    """
    with open(filename, encoding="utf-8", newline="") as fp:
        content = fp.read()
    original = content
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
            baseline, content, width=wrapnumber, desired_width=desired_width,
            punctuation_slop=punctuation_slop,
            whole_document=True,
        )
        shift = 0
        output = []
        position = 0
        for result in results:
            line = result["line"] + shift
            moves = result["moves"]
            chosen = result["aligned"]
            if chosen != result["before"]:
                reasons = []
                if result.get("reason"):
                    reasons.append(PROSE_FIX_REASONS[result["reason"]])
                elif not moves and result["linted"] != result["before"]:
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
                output.extend((content[position:result["start"]], chosen))
                position = result["stop"]
            shift += chosen.count("\n") - result["before"].count("\n")
        output.append(content[position:])
        content = "".join(output)
        # }}}
    else:
        # Without a reference, use the same planner with all prose editable.
        rows = content.splitlines(keepends=True)
        for row, replacement, kind in sorted(markdown_wrap_edits(
            content, wrapnumber, punctuation_slop, range(len(rows)), (),
        )):
            fixes.append({
                "line": row + 1, "reason": PROSE_FIX_REASONS[kind],
                "before": rows[row].rstrip("\r\n"),
                "after": replacement.rstrip("\r\n"),
            })
            rows[row] = replacement
        content = "".join(rows)
    # Syntax fixes can remove lines, so handle each batch from bottom to top.
    # Prose breaks were already decided together with the source layout.
    for _ in range(100):
        syntax = markdown_syntax(content)
        issues = markdown_lint_issues_from_text(
            content, wrapnumber=wrapnumber, punctuation_slop=punctuation_slop,
            check_wrapping=False, syntax=syntax,
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

    # Keep the file timestamp stable when the final plan changes nothing.
    if content != original:
        with open(filename, "w", encoding="utf-8", newline="") as fp:
            fp.write(content)
    else:
        fixes.clear()
    return {
        "fixes": fixes,
        "warnings": unclosed_markdown_spans(content, syntax=syntax),
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
