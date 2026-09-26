import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from pydifftools import zotero
from pydifftools.bibliography import (
    bib_entries,
    duplicate_reason,
    replace_bibliography_files,
    rewrite_citations,
)
from pydifftools.zotero import (
    read_bibtex,
    recover_bibliography,
    review_duplicate,
)


def test_bibtex_spans_preserve_macros_custom_fields_and_comments():
    text = r"""
% @article{not-an-entry}
@string{journal = "A Journal"}
@preamble{"Do not edit this"}
@comment{Nested {comment}}
@article(old,
  title = {A {nested} title with an escaped \} brace},
  journal = journal # " Supplement",
  author = "Author, A.",
  custom-field = {Private data, preserved},
)
"""
    (entry,) = bib_entries(text).values()
    assert entry.key == "old"
    assert entry.fields["journal"] == 'journal # " Supplement"'
    assert entry.fields["custom-field"] == "{Private data, preserved}"
    assert text[entry.start : entry.end].startswith("@article(old,")
    assert list(bib_entries(entry.render("new"))) == ["new"]


@pytest.mark.parametrize(
    "text",
    [
        "@article{key, title={oops}",
        "@book{key, title={a}, title={b}}",
        "@book{key} @book{key}",
    ],
)
def test_unsafe_bibtex_is_rejected(text):
    with pytest.raises(ValueError):
        bib_entries(text)


def test_duplicate_identifiers_and_bibliographic_similarity():
    base = {
        "id": "existing",
        "type": "article-journal",
        "title": "The signal-to-noise ratio of the NMR experiment",
        "author": [{"family": "Hoult", "given": "D. I."}],
        "issued": {"date-parts": [[1976]]},
    }
    incoming = {
        **base,
        "id": "new",
        "title": "The signal to noise ratio of the NMR experiment",
    }
    assert duplicate_reason(base, incoming)
    assert (
        duplicate_reason(
            {**base, "DOI": "https://doi.org/10.1234/ABC"},
            {**incoming, "DOI": "doi: 10.1234/abc"},
        )
        == "Same DOI"
    )
    assert (
        duplicate_reason(
            {**base, "DOI": "10.1/a"}, {**incoming, "DOI": "10.1/b"}
        )
        is None
    )
    assert (
        duplicate_reason(base, {**incoming, "title": "Unrelated research"})
        is None
    )
    assert (
        duplicate_reason(
            base, {**incoming, "issued": {"date-parts": [[1977]]}}
        )
        is None
    )
    assert duplicate_reason({}, {}) is None
    book = {"type": "book", "ISBN": "123-456", "edition": "1"}
    assert duplicate_reason(book, {**book, "ISBN": "123456"})
    assert duplicate_reason(book, {**book, "edition": "2"}) is None
    chapter = {**base, "type": "chapter", "page": "1-4"}
    assert duplicate_reason(chapter, {**chapter, "page": "5-8"}) is None


def test_citation_rewrite_changes_only_pandoc_citations():
    text = (
        "---\r\nnocite: '@OLD'\r\n---\r\n"
        "A citation @OLD; another [-@OLD, p. 4; @OLDish].\r\n"
        "Braced [@{OLD}].\r\n"
        "`@OLD` and \\@OLD and me@OLD.example\r\n"
        "[link](https://example.org/@OLD)\r\n"
        "<!-- @OLD -->\r\n"
        "```text\r\n@OLD\r\n```\r\n"
    )
    rewritten = rewrite_citations(text.encode(), {"OLD": "CHOSEN"}).decode()
    assert "A citation @CHOSEN" in rewritten
    assert "[-@CHOSEN, p. 4; @OLDish]" in rewritten
    assert "[@{CHOSEN}]" in rewritten
    assert "nocite: '@CHOSEN'" in rewritten
    for protected in [
        "`@OLD`",
        "\\@OLD",
        "me@OLD.example",
        "https://example.org/@OLD",
        "<!-- @OLD -->",
        "```text\r\n@OLD\r\n```",
    ]:
        assert protected in rewritten
    assert rewritten.count("\r\n") == text.count("\r\n")


def test_citation_rewrite_handles_headings_and_keys_with_shared_prefixes():
    text = b"# About @OLD\n\nCompare [@OLDlong; @OLD].\n"
    rewritten = rewrite_citations(text, {"OLD": "NEW", "OLDlong": "OTHER"})
    assert rewritten == b"# About @NEW\n\nCompare [@OTHER; @NEW].\n"
    assert rewrite_citations(text, {}) == text


@pytest.mark.parametrize(
    "action,chosen",
    [
        ("existing", "OLD"),
        ("incoming", "NEW"),
        ("merge", "OLD"),
        ("merge", "NEW"),
        ("both", "NEW"),
        ("skip", "OLD"),
    ],
)
def test_duplicate_choices_rewrite_unchosen_key(
    tmp_path, monkeypatch, action, chosen
):
    bib = tmp_path / "library.bib"
    original = (
        "% preserve this comment\n"
        "@article{OLD,title={Old title},doi={10.1/same},"
        "custom={Keep me},year={1976}}\n"
        "@book{other,title={Unrelated}}\n"
    )
    bib.write_text(original)
    source = tmp_path / "content.md"
    source.write_text("Compare @OLD and [@NEW]. `@OLD` and `@NEW`.\n")
    incoming = "@article{NEW,title={New title},doi={10.1/same},volume={24}}"
    monkeypatch.setattr(zotero, "export_bibtex", lambda _key: incoming)

    def review(matches, exported, filename):
        assert matches[0]["reason"] == "Same DOI"
        assert filename == source
        return {
            "action": action,
            "existing_key": "OLD",
            "key": chosen,
            "kind": "article",
            "fields": {**exported["fields"], **matches[0]["fields"]},
        }

    monkeypatch.setattr(zotero, "review_duplicate", review)
    resolved = recover_bibliography(bib, ["NEW"], source=source)
    entries = bib_entries(bib.read_text())
    assert "% preserve this comment" in bib.read_text()
    assert "@book{other,title={Unrelated}}" in bib.read_text()
    if action == "skip":
        assert resolved == []
        assert bib.read_text() == original
        assert "@OLD and [@NEW]" in source.read_text()
    elif action == "both":
        assert set(entries) == {"OLD", "NEW", "other"}
        assert "@OLD and [@NEW]" in source.read_text()
    else:
        assert resolved == ["NEW"]
        assert set(entries) == {chosen, "other"}
        assert f"@{chosen} and [@{chosen}]" in source.read_text()
        assert "`@OLD` and `@NEW`" in source.read_text()
        if action == "merge":
            assert entries[chosen].fields["custom"] == "{Keep me}"
            assert entries[chosen].fields["volume"] == "{24}"
            assert entries[chosen].fields["title"] == "{Old title}"
        elif action == "existing":
            assert bib.read_text() == original
        else:
            assert "custom" not in entries[chosen].fields
    assert len(read_bibtex(bib.read_bytes())) == len(entries)


def test_two_file_write_failure_rolls_back_bibliography(tmp_path, monkeypatch):
    bib = tmp_path / "library.bib"
    source = tmp_path / "content.md"
    bib.write_bytes(b"original bibliography")
    source.write_bytes(b"original source")
    replace = os.replace

    def fail_source(source_path, target):
        if target == source:
            raise PermissionError("source is locked")
        replace(source_path, target)

    monkeypatch.setattr(os, "replace", fail_source)
    with pytest.raises(PermissionError):
        replace_bibliography_files(
            {
                bib: (bib.read_bytes(), b"new bibliography"),
                source: (source.read_bytes(), b"new source"),
            }
        )
    assert bib.read_bytes() == b"original bibliography"
    assert source.read_bytes() == b"original source"
    assert set(tmp_path.iterdir()) == {bib, source}


def test_concurrent_edit_aborts_both_files(tmp_path):
    bib = tmp_path / "library.bib"
    source = tmp_path / "content.md"
    bib.write_bytes(b"original bibliography")
    source.write_bytes(b"user edit")
    with pytest.raises(ValueError, match="changed during"):
        replace_bibliography_files(
            {
                bib: (bib.read_bytes(), b"new bibliography"),
                source: (b"original source", b"rewritten source"),
            }
        )
    assert bib.read_bytes() == b"original bibliography"
    assert source.read_bytes() == b"user edit"
    assert set(tmp_path.iterdir()) == {bib, source}


def test_duplicate_review_subprocess_handles_cancel_and_errors(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "null", ""))
    monkeypatch.setattr(subprocess, "run", run)
    assert review_duplicate([], {}, "content.md") is None
    assert json.loads(run.call_args.kwargs["input"])["source"] == "content.md"
    run.return_value = subprocess.CompletedProcess([], 1, "", "Qt unavailable")
    with pytest.raises(ValueError, match="Qt unavailable"):
        review_duplicate([], {}, "content.md")


def test_qt_duplicate_merge_defaults_and_selection(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from pydifftools.citation_dialog import DuplicateDialog

    app = QApplication.instance() or QApplication([])
    existing = {
        "key": "OLD",
        "kind": "article",
        "reason": "Same DOI",
        "fields": {"title": "{Old title}", "custom": "{Keep}"},
    }
    incoming = {
        "key": "NEW",
        "kind": "article",
        "fields": {"title": "{New title}", "volume": "{24}"},
    }
    dialog = DuplicateDialog([existing], incoming, "content.md")
    assert dialog.selectors["citation key"].currentData() == "OLD"
    assert dialog.selectors["title"].currentData() == "{Old title}"
    assert dialog.selectors["custom"].currentData() == "{Keep}"
    assert dialog.selectors["volume"].currentData() == "{24}"
    dialog.selectors["citation key"].setCurrentIndex(1)
    dialog.selectors["title"].setCurrentIndex(1)
    dialog.buttons["merge"].click()
    assert dialog.decision["key"] == "NEW"
    assert dialog.decision["fields"]["title"] == "{New title}"
    dialog.close()
    app.processEvents()
