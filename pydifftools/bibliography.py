"""Lossless BibTeX edits and citation-aware Markdown key changes.

Pandoc remains the semantic parser. The small scanner here only locates raw
entry/field boundaries, preserving macros, custom fields and untouched text.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata


def scan_bibtex(text, start, stops):
    """Locate an unquoted delimiter outside balanced braces."""
    depth = 0
    quoted = False
    position = start
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "%" and depth == 0 and not quoted:
            newline = text.find("\n", position)
            position = len(text) if newline < 0 else newline + 1
            continue
        if depth == 0 and not quoted and char in stops:
            return position
        if char == '"' and depth == 0:
            quoted = not quoted
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced BibTeX braces")
        position += 1
    if depth or quoted:
        raise ValueError("unterminated BibTeX value")
    return position


@dataclass
class BibEntry:
    start: int
    end: int
    kind: str
    key: str
    fields: dict

    def render(self, key=None, fields=None):
        selected = self.fields if fields is None else fields
        body = ",\n".join(
            f"  {name} = {value}" for name, value in selected.items()
        )
        return f"@{self.kind}{{{key or self.key},\n{body}\n}}"


def bib_entry_list(text):
    """Every entry's span and raw fields in order, including repeated keys."""
    entries = []
    position = 0
    while position < len(text):
        position = scan_bibtex(text, position, "@")
        if position == len(text):
            break
        header = re.match(r"@([\w-]+)\s*([{(])", text[position:])
        if not header:
            position += 1
            continue
        start = position
        kind = header[1].lower()
        position += header.end()
        closing = "}" if header[2] == "{" else ")"
        end = scan_bibtex(text, position, closing)
        if end == len(text):
            raise ValueError("unterminated BibTeX entry")
        body = text[position:end]
        position = end + 1
        if kind in {"comment", "preamble", "string"}:
            continue
        key_end = scan_bibtex(body, 0, ",")
        key = body[:key_end].strip()
        fields = {}
        offset = key_end + 1
        while offset < len(body):
            whitespace = re.match(r"(?:\s|%[^\n]*(?:\n|$))*", body[offset:])
            offset += whitespace.end()
            if offset == len(body):
                break
            field = re.match(r"([\w-]+)\s*=\s*", body[offset:])
            if not field:
                raise ValueError(f"cannot safely edit BibTeX fields in {key}")
            offset += field.end()
            boundary = scan_bibtex(body, offset, ",")
            name = field[1].lower()
            if name in fields:
                raise ValueError(f"duplicate BibTeX field {name} in {key}")
            fields[name] = body[offset:boundary].strip()
            offset = boundary + 1
        entries.append(BibEntry(start, end + 1, kind, key, fields))
    return entries


def bib_entries(text):
    """Index entry spans and raw fields without reserializing them."""
    entries = {}
    for entry in bib_entry_list(text):
        if entry.key in entries:
            raise ValueError(f"duplicate BibTeX key {entry.key}")
        entries[entry.key] = entry
    return entries


def normalized_text(value):
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value)))
    text = unicodedata.normalize("NFKD", text).casefold()
    return "".join(char for char in text if char.isalnum())


def duplicate_reason(existing, incoming):
    """Identify likely duplicates for human review using Pandoc CSL records.

    Inspired by JabRef's identifier-first, bibliographic-field comparison:
    https://github.com/JabRef/jabref/blob/main/jablib/src/main/java/org/jabref/
    logic/database/DuplicateCheck.java. No Java code is copied.
    """
    identifiers = []
    for record in (existing, incoming):
        doi = str(record.get("DOI", "")).strip().casefold()
        identifiers.append(
            re.sub(r"^(?:https?://(?:dx\.)?doi.org/|doi:\s*)", "", doi)
        )
    if all(identifiers):
        return "Same DOI" if identifiers[0] == identifiers[1] else None
    if existing.get("type") != incoming.get("type"):
        return None
    for field in ("edition", "chapter-number"):
        if existing.get(field) and incoming.get(field):
            if normalized_text(existing[field]) != normalized_text(
                incoming[field]
            ):
                return None
    if existing.get("type") == "chapter":
        if normalized_text(existing.get("page")) != normalized_text(
            incoming.get("page")
        ):
            return None
    if existing.get("type") == "book":
        isbn = normalized_text(existing.get("ISBN", ""))
        if isbn and isbn == normalized_text(incoming.get("ISBN", "")):
            return "Same ISBN and edition"
    titles = [
        normalized_text(record.get("title", ""))
        for record in (existing, incoming)
    ]
    authors = [
        record.get("author", record.get("editor", []))
        for record in (existing, incoming)
    ]
    years = [
        record.get("issued", {}).get("date-parts", [[]])[0][:1]
        for record in (existing, incoming)
    ]
    if not all(titles) or not all(authors) or not all(years):
        return None
    surnames = [
        normalized_text(names[0].get("family", names[0].get("literal", "")))
        for names in authors
    ]
    similar_title = titles[0] == titles[1] or (
        min(map(len, titles)) >= 20
        and SequenceMatcher(None, *titles).ratio() >= 0.92
    )
    if (
        similar_title
        and surnames[0]
        and surnames[0] == surnames[1]
        and years[0] == years[1]
    ):
        return "Similar title, same first author and year"
    return None


def markdown_ast(text, renames=None):
    """Parse Markdown, optionally normalizing citation IDs for comparison."""
    completed = subprocess.run(
        ["pandoc", "--from=markdown-auto_identifiers", "--to=json"],
        input=text.encode("utf-8"),
        capture_output=True,
    )
    if completed.returncode:
        raise ValueError("cannot parse Markdown to update citation keys")
    tree = json.loads(completed.stdout)
    if renames is not None:
        pending = [tree]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if node.get("t") == "Cite":
                    # Pandoc stores both parsed citations and their source
                    # spelling; spelling changes when a key is renamed.
                    node["c"][1] = []
                    for citation in node["c"][0]:
                        old = citation["citationId"]
                        citation["citationId"] = renames.get(old, old)
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
    return tree


def rewrite_citations(markdown, renames):
    """Replace citation tokens, accepting edits only when Pandoc confirms them.

    AST comparison protects code, links, email addresses, comments, ordinary
    text and keys with a shared prefix, while retaining original formatting.
    """
    text = markdown.decode("utf-8")
    if not renames:
        return markdown
    expected = markdown_ast(text, renames)
    keys = sorted(renames, key=len, reverse=True)
    pattern = re.compile(
        r"@(?:\{("
        + "|".join(map(re.escape, keys))
        + r")\}|("
        + "|".join(map(re.escape, keys))
        + r"))"
    )
    for match in reversed(list(pattern.finditer(text))):
        old = match[1] or match[2]
        replacement = (
            "@{" + renames[old] + "}" if match[1] else "@" + renames[old]
        )
        candidate = text[: match.start()] + replacement + text[match.end() :]
        if markdown_ast(candidate, renames) == expected:
            text = candidate
    if markdown_ast(text, {}) != expected:
        raise ValueError("could not safely update all Markdown citation keys")
    return text.encode("utf-8")


def replace_bibliography_files(changes):
    """Stage validated replacements and roll back if a later replacement fails.

    Changes map paths to (original bytes, replacement bytes). Files are closed
    before replacement for Windows. A crash across two replacements cannot be
    atomic; ordinary write failures are rolled back without overwriting edits.
    """
    staged = {}
    backups = {}
    committed = []
    temporaries = []
    try:
        for path, (original, replacement) in changes.items():
            path = Path(path)
            if replacement == original:
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
            if not mode & 0o222 or not os.access(path, os.W_OK):
                raise PermissionError(f"file is not writable: {path}")
            for content, targets in [
                (original, backups),
                (replacement, staged),
            ]:
                with tempfile.NamedTemporaryFile(
                    dir=path.parent, prefix=f".{path.name}.", delete=False
                ) as output:
                    temporary = Path(output.name)
                    temporaries.append(temporary)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, mode)
                targets[path] = temporary
        for path, (original, _) in changes.items():
            if Path(path).read_bytes() != original:
                raise ValueError(f"file changed during Zotero lookup: {path}")
        for path in staged:
            if path.read_bytes() != changes[path][0]:
                raise ValueError(f"file changed during Zotero lookup: {path}")
            os.replace(staged[path], path)
            committed.append(path)
    except (OSError, ValueError):
        for path in reversed(committed):
            if path.read_bytes() == changes[path][1]:
                try:
                    os.replace(backups[path], path)
                except OSError as exc:
                    # Keep a recovery copy if even rollback is prevented.
                    temporaries.remove(backups[path])
                    raise OSError(
                        f"could not restore {path}; original saved at "
                        f"{backups[path]}"
                    ) from exc
        raise
    finally:
        for temporary in temporaries:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                print(
                    f"cpb: cannot remove {temporary}: {exc}", file=sys.stderr
                )
