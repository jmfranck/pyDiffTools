"""Build source positions without adding text or elements to preview bodies."""

from difflib import SequenceMatcher
import json
import re
import uuid
from pathlib import Path

from lxml import html


BLOCKS = "//p | //li[not(p)] | //dt | //dd[not(p)] | //td | //th"
SPACE = re.compile(r"[ \t\r\n\f]+")
WORDS = re.compile(
    r"""\{[^}]*\}|https?://[^\s<>]+|<[^>]*>|"""
    r"""\[[^\]]*\](?:\([^)]*\))?|@[\w:./-]+|"""
    r"""\$[^$]*\$|`[^`]*`|\*[^*]*\*|_[^_]*_|"""
    r"""["“][^"”]*["”]|(?<!\S)[^\W_][\w-]*"""
)
# MathJax replaces its input text after load. Offsets skip math in both trees.
TEXT = (
    ".//text()[not(ancestor::math or ancestor::*["
    "contains(concat(' ', normalize-space(@class), ' '), ' math ')])]"
)
MAP_ATTRIBUTE = "data-pydifft-line-map"


def mark_source_lines(staged, source):
    """Add plain-text prefixes to safe words in the conversion input."""
    nonce = "LINENO" + uuid.uuid4().hex[:12] + "X"
    original = Path(source).read_text(encoding="utf-8").splitlines()
    lines = staged.splitlines(keepends=True)
    provenance = {}
    # {{{ Track unchanged lines across QMDB's staged code and include edits.
    for a, b, size in SequenceMatcher(
        None, original, [line.rstrip("\r\n") for line in lines],
        autojunk=False,
    ).get_matching_blocks():
        provenance.update((b + i, a + i + 1) for i in range(size))
    # }}}
    fence = None
    yaml = bool(lines and lines[0].strip() == "---")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if yaml:
            if index and stripped in {"---", "..."}:
                yaml = False
            continue
        if fence == "$":
            if re.search(r"(?<!\\)\$\$", stripped):
                fence = None
            continue
        if fence is None and stripped.startswith("$$"):
            if not re.search(r"(?<!\\)\$\$", stripped[2:]):
                fence = "$"
            continue
        delimiter = re.match(r"^\s*(`{3,}|~{3,}|:{3,})", line)
        if delimiter:
            kind = delimiter[1][0]
            if fence == kind:
                fence = None
            elif fence is None:
                fence = kind
            continue
        if fence or index not in provenance or re.match(
            r"^\s*(?:#|<|\[.+?\]:|[=-]+\s*$)|^ {4}|^\t", line
        ):
            continue
        if index + 1 < len(lines) and re.fullmatch(
            r"[ 	]*(?:=+|-+)[ 	]*", lines[index + 1].rstrip("\r\n")
        ):
            continue
        prefix = re.match(r"^\s*(?:(?:[-+*]|\d+[.)]|>)\s+)*", line)
        for word in WORDS.finditer(line, prefix.end()):
            if word[0].isalpha() and not re.search(
                r"\\$", line[:word.start()]
            ):
                at = word.start()
                lines[index] = (
                    line[:at] + nonce + f"{provenance[index]:07d}X"
                    + line[at:]
                )
                break
    return "".join(lines), nonce


def extract_source_lines(
    output, nonce, source, *, project=None, code_positions=(),
    normalize_html=None, marked_html=None,
):
    """Strip the conversion prefixes and record their final HTML positions."""
    marker = re.compile(nonce + r"(\d+)X")
    output = Path(output)
    if marked_html is None:
        marked_html = output.read_text(encoding="utf-8")
    normal_html = marker.sub("", marked_html)
    source = Path(source).resolve()
    source_id = str(source.relative_to(project) if project else source)
    marked = html.document_fromstring(
        normalize_html(marked_html) if normalize_html else marked_html
    )
    rendered = html.document_fromstring(
        normalize_html(normal_html) if normalize_html else normal_html
    )
    for marked_block, block in zip(
        marked.xpath(BLOCKS), rendered.xpath(BLOCKS)
    ):
        value = "".join(marked_block.xpath(TEXT))
        if marker.sub("", value) != "".join(block.xpath(TEXT)):
            continue
        positions = []
        for found in marker.finditer(value):
            left = SPACE.sub(" ", marker.sub("", value[:found.start()]))
            offset = len(left.lstrip(" ").encode("utf-16-le")) // 2
            positions.append([offset, int(found[1])])
        if positions:
            block.set(MAP_ATTRIBUTE, json.dumps([source_id, positions]))
    if project is None:
        finish_source_map(rendered)
        script = rendered.find("head/script[@id='pydifft-line-map']")
        if script is not None:
            normal_html = re.sub(
                r"</head\s*>",
                lambda m: html.tostring(script, encoding="unicode") + m[0],
                normal_html, count=1, flags=re.IGNORECASE,
            )
        output.write_text(normal_html, "utf-8")
        return
    for node in rendered.xpath("//*[@data-script][@data-index]"):
        index = int(node.get("data-index")) - 1
        if 0 <= index < len(code_positions):
            node.set(MAP_ATTRIBUTE, json.dumps(
                [source_id, [[0, code_positions[index]]]]
            ))
    Path(output).write_text(
        html.tostring(rendered.getroottree(), encoding="unicode"), "utf-8"
    )


def finish_source_map(root, project=None):
    """Move temporary block metadata to a head script using element paths."""
    entries = []
    body = root.find("body")
    head = root.find("head")
    if body is None or head is None:
        return
    for node in body.xpath(f".//*[@{MAP_ATTRIBUTE}]"):
        source, positions = json.loads(node.attrib.pop(MAP_ATTRIBUTE))
        path = []
        current = node
        while current is not body:
            path.append(sum(isinstance(s.tag, str)
                            for s in current.itersiblings(preceding=True)))
            current = current.getparent()
        if project is not None:
            source = str((project / source).resolve())
        entries.append([path[::-1], source, positions])
    if entries:
        script = html.Element(
            "script", id="pydifft-line-map", type="application/json"
        )
        script.text = json.dumps(entries).replace("<", "\\u003c")
        head.append(script)
