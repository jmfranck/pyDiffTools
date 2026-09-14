import re
import sys
import itertools
from dataclasses import dataclass, field

from .command_registry import register_command

DISPLAY_MATH = re.compile(r"(?<!\\)(?:\\\\)*(\$\$)")


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
    for paragraph in re.split(r"(\n(?:[ \t]*\n)+)", text):
        if not paragraph.strip():
            output.append(paragraph)
            continue
        leading = "\n" if paragraph.startswith("\n") else ""
        trailing = "\n" if paragraph.endswith("\n") else ""
        parts = re.split(r"([^\.!?]{3}[\.!?])[ \n]", paragraph.strip("\n"))
        sentences = [
            parts[j] + (parts[j + 1] if j + 1 < len(parts) else "")
            for j in range(0, len(parts), 2)
        ]
        sentences = [
            part
            for sentence in sentences
            for part in re.split(
                r"(\\(?:begin|end|usepackage|newcommand|section"
                r"|subsection|subsubsection|paragraph|input){[^}]*})",
                sentence,
            )
        ]
        lines = []
        indentation = 0
        for sentence in sentences:
            words = [word for word in re.split("[ \n]+", sentence) if word]
            # Mark existing whitespace at the two boundaries of paired math.
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
            if filetype == "latex":
                indentation = 0
            offset = 0
            while words:
                counts = list(
                    itertools.accumulate(len(word) + 1 for word in words)
                )
                upto = min(
                    range(len(counts)),
                    key=lambda j: abs(counts[j] - wrapnumber),
                )
                candidates = [
                    j
                    for j, word in enumerate(words)
                    if (len(word) > 1 and word[-1] in ",;:)-")
                    or offset + j in boundaries
                ]
                if candidates:
                    punct = min(
                        candidates, key=lambda j: abs(counts[j] - wrapnumber)
                    )
                    if punct < upto and upto - punct < punctuation_slop:
                        upto = punct
                lines.append(" " * indentation + " ".join(words[: upto + 1]))
                words = words[upto + 1 :]
                offset += upto + 1
                if indentation == 0:
                    indentation = indent_amount
        output.append(leading + "\n".join(lines) + trailing)
    return "".join(output)


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
)
def wr(filename, wrapnumber=45, punctuation_slop=20, cleanoo=False, i=-1):
    indent_amount = i if i != -1 else 4
    stupid_strip = cleanoo
    if filename == "-":
        filename = None
    # {{{ load the file
    if filename is not None:
        with open(filename, encoding="utf-8") as fp:
            alltext = fp.read()
        # {{{ determine if the filetype is latex or markdown
        file_extension = filename.split(".")[-1]
        if file_extension == "tex":
            filetype = "latex"
        elif file_extension == "md":
            # print("identified as markdown!!")
            filetype = "markdown"
        elif file_extension == "qmd":
            # print("identified as markdown!!")
            filetype = "markdown"
        if filetype == "markdown":
            if i == -1:
                indent_amount = 0
        # }}}
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        fp = sys.stdin
        alltext = fp.read()
        filetype = "latex"
    # }}}
    # {{{ strip stupid commands that appear in openoffice conversion
    if stupid_strip:
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
    if filetype == "markdown":
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
    if filename is None:
        sys.stdout.write(result)
    else:
        with open(filename, "w", encoding="utf-8") as fp:
            fp.write(result)
