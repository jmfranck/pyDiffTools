"""Read local Better BibTeX exports and safely extend a bibliography."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.request import Request, urlopen

from .bibliography import (
    bib_entries,
    duplicate_reason,
    replace_bibliography_files,
    rewrite_citations,
)


def call_zotero(method, params):
    """Call the local API; distinguish transport and JSON-RPC errors."""
    request = Request(
        "http://127.0.0.1:23119/better-bibtex/json-rpc",
        data=json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise ValueError("invalid Better BibTeX response")
    if "error" in payload:
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise ValueError(f"Better BibTeX: {message}")
    if payload.get("id") != 1 or "result" not in payload:
        raise ValueError("invalid Better BibTeX response")
    return payload["result"]


def export_bibtex(citation_key):
    """Export one exact key from Zotero's default personal library.

    Connection errors propagate as OSError; invalid responses and unresolved
    or ambiguous keys raise ValueError. Zotero and Better BibTeX must run.
    """
    exported = call_zotero("item.export", [[citation_key], "Better BibTeX"])
    if not isinstance(exported, str) or not exported:
        raise ValueError("invalid Better BibTeX export")
    return exported


def zotero_notice():
    """Return a nonblocking Qt notice if the local API is unavailable."""
    try:
        ready = call_zotero("api.ready", [])
        if not isinstance(ready, dict) or not ready.get("betterbibtex"):
            raise ValueError("Better BibTeX is not ready")
    except (OSError, ValueError):
        message = (
            "Zotero is unavailable. Your document will still build.\n\n"
            "With Zotero running, pydifft cpb can pull new citations directly "
            "from your library, so you don't have to update the bibliography "
            "file yourself.\n\n"
            "Start Zotero with the Better BibTeX plugin enabled to use this "
            "feature."
        )
        print(f"cpb: {message}", file=sys.stderr)
        script = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv[:1])
QMessageBox.information(None, "pydifft cpb — Zotero", sys.argv[1])
"""
        try:
            return subprocess.Popen(
                [sys.executable, "-c", script, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            print(f"cpb: could not show Zotero notice: {exc}", file=sys.stderr)
    return None


def read_bibtex(data):
    """Use Pandoc's own reader to validate BibTeX and return CSL records."""
    completed = subprocess.run(
        ["pandoc", "--from=bibtex", "--to=csljson"],
        input=data,
        capture_output=True,
    )
    if completed.returncode or completed.stderr.strip():
        raise ValueError(
            "invalid BibTeX: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    records = json.loads(completed.stdout)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) or not isinstance(record.get("id"), str)
        for record in records
    ):
        raise ValueError("invalid Pandoc bibliography response")
    return records


def review_duplicate(matches, incoming, source):
    """Run the Qt review on the GUI thread of an isolated Python process."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("citation_dialog.py"))],
        input=json.dumps(
            {"matches": matches, "incoming": incoming, "source": str(source)}
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ValueError(f"duplicate review failed: {result.stderr.strip()}")
    decision = json.loads(result.stdout)
    if decision is not None and not isinstance(decision, dict):
        raise ValueError("invalid duplicate review response")
    return decision


def recover_bibliography(bibliography, citation_keys, source=None):
    """Recover citations, reviewing duplicates before bibliography edits.

    Return resolved keys only after committing the changes. Existing entries
    retain their bytes unless the user explicitly replaces or merges them.
    """
    resolved = []
    try:
        if bibliography is None:
            raise ValueError("no single active local .bib bibliography")
        path = Path(bibliography).resolve()
        if path.suffix.lower() != ".bib":
            raise ValueError("the active bibliography is not a .bib file")
        original_stat = path.stat()
        if not stat.S_ISREG(original_stat.st_mode):
            raise ValueError("the active bibliography is not a regular file")
        if not original_stat.st_mode & 0o222 or not os.access(path, os.W_OK):
            raise PermissionError(f"bibliography is not writable: {path}")
        original = path.read_bytes()
        candidate = original.decode("utf-8")
        records = read_bibtex(original)
        source_path = Path(source).resolve() if source is not None else None
        source_original = source_path.read_bytes() if source_path else None
        renames = {}
        # {{{ retrieve and validate independent citation exports
        for key in dict.fromkeys(citation_keys):
            entries = bib_entries(candidate)
            if key in entries or key in renames:
                continue
            try:
                exported = export_bibtex(key)
                incoming_records = read_bibtex(exported.encode("utf-8"))
                if [record["id"] for record in incoming_records] != [key]:
                    raise ValueError("export did not contain exactly this key")
                incoming = bib_entries(exported)[key]
            except OSError as exc:
                print(f"cpb: Zotero unavailable: {exc}", file=sys.stderr)
                break
            except ValueError as exc:
                print(f"cpb: could not retrieve {key}: {exc}", file=sys.stderr)
                continue
            matches = []
            for record in records:
                reason = duplicate_reason(record, incoming_records[0])
                if reason:
                    entry = entries[record["id"]]
                    matches.append(
                        {
                            "key": entry.key,
                            "kind": entry.kind,
                            "fields": entry.fields,
                            "reason": reason,
                        }
                    )
            if matches:
                try:
                    if source_path is None:
                        raise ValueError(
                            "duplicate review needs a Markdown source"
                        )
                    decision = review_duplicate(
                        matches,
                        {
                            "key": incoming.key,
                            "kind": incoming.kind,
                            "fields": incoming.fields,
                        },
                        source_path,
                    )
                    if not decision or decision.get("action") == "skip":
                        continue
                    action = decision.get("action")
                    if action not in {"existing", "incoming", "merge", "both"}:
                        raise ValueError("invalid duplicate review decision")
                    selected = decision.get("existing_key")
                    if selected not in {match["key"] for match in matches}:
                        raise ValueError("invalid existing citation selection")
                    existing = entries[selected]
                    if action == "existing":
                        chosen = selected
                    elif action in {"incoming", "merge"}:
                        chosen = key
                        if action == "merge":
                            chosen = decision.get("key")
                            if chosen not in {selected, key}:
                                raise ValueError("invalid merged citation key")
                            incoming.kind = decision["kind"]
                            replacement = incoming.render(
                                chosen, decision["fields"]
                            )
                        else:
                            replacement = exported[
                                incoming.start : incoming.end
                            ]
                        candidate = (
                            candidate[: existing.start]
                            + replacement
                            + candidate[existing.end :]
                        )
                    else:
                        chosen = key
                        candidate += "\n\n" + exported.rstrip() + "\n"
                    if action != "both":
                        unchosen = key if chosen == selected else selected
                        renames[unchosen] = chosen
                except (OSError, ValueError) as exc:
                    print(
                        f"cpb: skipped duplicate {key}: {exc}", file=sys.stderr
                    )
                    continue
            else:
                candidate += "\n\n" + exported.rstrip() + "\n"
            records = read_bibtex(candidate.encode("utf-8"))
            resolved.append(key)
        # }}}
        if not resolved:
            return []
        # {{{ validate the complete result and stage bibliography/source edits
        if set(bib_entries(candidate)) != {record["id"] for record in records}:
            raise ValueError("combined bibliography changed citation keys")
        changes = {path: (original, candidate.encode("utf-8"))}
        if renames:
            for old in renames:
                visited = {old}
                chosen = renames[old]
                while chosen in renames:
                    if chosen in visited:
                        raise ValueError("cyclic citation key selection")
                    visited.add(chosen)
                    chosen = renames[chosen]
                renames[old] = chosen
            rewritten = rewrite_citations(source_original, renames)
            changes[source_path] = (source_original, rewritten)
        elif (
            source_path is not None
            and source_path.read_bytes() != source_original
        ):
            raise ValueError("Markdown changed during Zotero lookup")
        replace_bibliography_files(changes)
        # }}}
    except (OSError, ValueError) as exc:
        print(f"cpb: bibliography recovery skipped: {exc}", file=sys.stderr)
        return []
    print(f"cpb: recovered {', '.join(resolved)} in {bibliography}")
    for old, chosen in renames.items():
        print(f"cpb: replaced @{old} with @{chosen} in {source}")
    return resolved
