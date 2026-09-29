import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from pydifftools import continuous, zotero
from pydifftools.zotero import (
    call_zotero,
    export_bibtex,
    read_bibtex,
    recover_bibliography,
    zotero_notice,
)


@pytest.fixture
def exports():
    return json.loads(
        (Path(__file__).parent / "fixtures/zotero/exports.json").read_text()
    )


@pytest.fixture
def local_api(monkeypatch, exports):
    requests = []

    def respond(request, timeout):
        payload = json.loads(request.data)
        assert request.full_url == (
            "http://127.0.0.1:23119/better-bibtex/json-rpc"
        )
        assert request.get_header("Content-type") == "application/json"
        assert timeout == 5
        assert payload["method"] == "item.export"
        assert payload["params"][1] == "Better BibTeX"
        (key,) = payload["params"][0]
        requests.append(key)
        return io.BytesIO(json.dumps(exports[key]).encode())

    monkeypatch.setattr(zotero, "urlopen", respond)
    return requests


@pytest.fixture
def bibliography(tmp_path):
    path = tmp_path / "references.bib"
    path.write_bytes(b"% Keep formatting\r\n@book{old,title={Old}}\r\n")
    return path


@pytest.mark.skipif(
    os.environ.get("PYDIFFTOOLS_ZOTERO_LIVE") != "1",
    reason="opt in to the running local Zotero smoke test",
)
def test_live_hoult_export():
    records = read_bibtex(export_bibtex("Hoult1976SigRatNuc").encode())
    (record,) = records
    assert record["id"] == "Hoult1976SigRatNuc"
    assert [author["family"] for author in record["author"]] == [
        "Hoult",
        "Richards",
    ]
    assert record["issued"]["date-parts"][0][0] == 1976
    assert record["DOI"] == "10.1016/0022-2364(76)90233-X"


@pytest.mark.skipif(
    os.environ.get("PYDIFFTOOLS_ZOTERO_LIVE") != "1",
    reason="opt in to the local eigenmode/Zotero integration test",
)
def test_live_eigenmode_copy(tmp_path, monkeypatch):
    from selenium import webdriver
    from pydifftools import command_line

    original = Path.home() / "notebook/papers/eigenmode"
    before = {
        path.relative_to(original): hashlib.sha256(path.read_bytes()).digest()
        for path in original.rglob("*")
        if path.is_file()
    }
    project = tmp_path / "eigenmode"
    shutil.copytree(original, project)
    source = project / "content.md"
    monkeypatch.chdir(project)
    monkeypatch.setattr(continuous, "FORWARD_SEARCH_PORT", 0)
    monkeypatch.setattr(continuous, "Observer", Mock)
    monkeypatch.setattr(
        continuous, "confirm_restore_comment_filter", lambda _mode: True
    )
    monkeypatch.setattr(continuous, "zotero_notice", lambda: None)
    monkeypatch.setattr(
        command_line.update_check,
        "check_update",
        lambda _package: ("test", "test", False),
    )
    monkeypatch.setattr(
        zotero,
        "review_duplicate",
        lambda matches, *_args: {
            "action": "existing",
            "existing_key": matches[0]["key"],
        },
    )
    browser = Mock(window_handles=[])
    monkeypatch.setattr(webdriver, "Chrome", lambda: browser)
    try:
        command_line.main(["cpb", source.name])
        assert (
            'id="ref-Hoult1976SigRatNuc"'
            in (project / "content.html").read_text()
        )
        assert "Hoult1976SigRatNuc" in (project / "Resonator.bib").read_text()
        browser.get.assert_called_once()
    finally:
        after = {
            path.relative_to(original): hashlib.sha256(
                path.read_bytes()
            ).digest()
            for path in original.rglob("*")
            if path.is_file()
        }
        assert before == after


def test_recovery_preserves_bytes_permissions_and_is_idempotent(
    bibliography, local_api
):
    before = bibliography.read_bytes()
    mode = stat.S_IMODE(bibliography.stat().st_mode)
    keys = ["Hoult1976SigRatNuc", "Hoult1976SigRatNuc"]
    assert recover_bibliography(bibliography, keys) == keys[:1]
    after = bibliography.read_bytes()
    assert after.startswith(before)
    assert stat.S_IMODE(bibliography.stat().st_mode) == mode
    assert recover_bibliography(bibliography, keys) == []
    assert bibliography.read_bytes() == after
    assert local_api == keys[:1]
    assert not list(bibliography.parent.glob(".references.bib.*"))


def test_eigenmode_partial_recovery_with_real_pandoc(
    tmp_path, monkeypatch, local_api, capfd
):
    fixture = Path(__file__).parent / "fixtures/zotero"
    for name in ["content.md", "Resonator.bib"]:
        shutil.copyfile(fixture / name, tmp_path / name)
    source = tmp_path / "content.md"
    html = tmp_path / "content.html"
    builds = []
    real_run = subprocess.run

    def record_build(command, **kwargs):
        if "--citeproc" in command:
            builds.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_build)
    continuous.run_pandoc(str(source), str(html))
    assert len(builds) == 2
    assert set(local_api) == {
        "Hoult1976SigRatNuc",
        "Doll2012LiqStaDNP",
        "Guinness2024SepDetCha",
    }
    assert 'id="ref-Hoult1976SigRatNuc"' in html.read_text()
    assert 'id="ref-Doll2012LiqStaDNP"' in html.read_text()
    assert (
        "unresolved citations: Guinness2024SepDetCha" in capfd.readouterr().err
    )
    before = (tmp_path / "Resonator.bib").read_bytes()
    continuous.run_pandoc(str(source), str(html))
    assert len(builds) == 3
    assert local_api.count("Hoult1976SigRatNuc") == 1
    assert (tmp_path / "Resonator.bib").read_bytes() == before


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"jsonrpc": "2.0", "id": 7, "result": "text"},
        {"jsonrpc": "2.0", "id": 1, "result": []},
        {"jsonrpc": "2.0", "id": 1, "result": ""},
        {"jsonrpc": "2.0", "error": {"message": "duplicates found: key"}},
    ],
)
def test_export_rejects_invalid_responses(monkeypatch, payload):
    monkeypatch.setattr(
        zotero,
        "urlopen",
        lambda *_a, **_k: io.BytesIO(json.dumps(payload).encode()),
    )
    with pytest.raises(ValueError):
        export_bibtex("key")


@pytest.mark.parametrize(
    "response",
    [
        "not JSON",
        '{"jsonrpc":"2.0","id":1,"result":"@book{wrong}"}',
        '{"jsonrpc":"2.0","id":1,"result":"@book{key,title={oops}"}',
        '{"jsonrpc":"2.0","id":1,"result":"@book{key} @book{key}"}',
    ],
)
def test_bad_exports_leave_bibliography_untouched(
    monkeypatch, bibliography, response
):
    monkeypatch.setattr(
        zotero, "urlopen", lambda *_a, **_k: io.BytesIO(response.encode())
    )
    original = bibliography.read_bytes()
    assert recover_bibliography(bibliography, ["key"]) == []
    assert bibliography.read_bytes() == original


@pytest.mark.parametrize("error", [URLError("offline"), TimeoutError()])
def test_unavailable_service_stops_lookup(monkeypatch, bibliography, error):
    lookup = Mock(side_effect=error)
    monkeypatch.setattr(zotero, "urlopen", lookup)
    original = bibliography.read_bytes()
    assert recover_bibliography(bibliography, ["one", "two"]) == []
    assert lookup.call_count == 1
    assert bibliography.read_bytes() == original


@pytest.mark.parametrize("failure", ["edit", "replace", "readonly"])
def test_update_failure_preserves_original(
    monkeypatch, bibliography, exports, failure
):
    original = bibliography.read_bytes()
    expected = original
    if failure == "readonly":
        bibliography.chmod(stat.S_IREAD)
    elif failure == "replace":
        monkeypatch.setattr(os, "replace", Mock(side_effect=PermissionError()))
    else:
        expected = original + b"% concurrent edit\n"

    def fetch(key):
        if failure == "edit":
            bibliography.write_bytes(expected)
        return exports[key]["result"]

    monkeypatch.setattr(zotero, "export_bibtex", fetch)
    try:
        assert recover_bibliography(bibliography, ["Hoult1976SigRatNuc"]) == []
        assert bibliography.read_bytes() == expected
        assert not list(bibliography.parent.glob(".references.bib.*"))
    finally:
        bibliography.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.real_notice
def test_notice_is_informational_and_waits_for_ok(monkeypatch):
    monkeypatch.setattr(zotero, "urlopen", Mock(side_effect=URLError("off")))
    launch = Mock()
    monkeypatch.setattr(zotero.subprocess, "run", launch)
    zotero_notice()
    # subprocess.run returns only once the window is dismissed
    args = launch.call_args.args[0]
    assert "QMessageBox.information" in args[2]
    assert "will still build" in args[3]
    assert "don't have to update" in args[3]


@pytest.mark.real_notice
def test_ready_zotero_needs_no_notice(monkeypatch):
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"zotero": "8", "betterbibtex": "8"},
    }
    monkeypatch.setattr(
        zotero,
        "urlopen",
        lambda *_a, **_k: io.BytesIO(json.dumps(response).encode()),
    )
    launch = Mock()
    monkeypatch.setattr(zotero.subprocess, "run", launch)
    assert call_zotero("api.ready", []) == response["result"]
    zotero_notice()
    launch.assert_not_called()


@pytest.mark.parametrize(
    "metadata",
    [
        "bibliography: refs/library.bib",
        "bibliography: [refs/library.bib]",
    ],
)
def test_explicit_bibliography_wins_and_resolves_from_source(
    tmp_path, local_api, metadata
):
    project = tmp_path / "project"
    project.mkdir()
    refs = project / "refs"
    refs.mkdir()
    bib = refs / "library.bib"
    bib.write_text("% empty bibliography\n")
    for name in ["one.bib", "two.bib"]:
        (project / name).write_text("% unrelated\n")
    source = project / "content.md"
    source.write_text(f"---\n{metadata}\n---\n[@Hoult1976SigRatNuc]\n")
    html = project / "content.html"
    continuous.run_pandoc(str(source), str(html))
    assert local_api == ["Hoult1976SigRatNuc"]
    assert 'id="ref-Hoult1976SigRatNuc"' in html.read_text()
    assert (project / "one.bib").read_text() == "% unrelated\n"


def test_no_missing_citations_does_not_contact_zotero(tmp_path, monkeypatch):
    source = tmp_path / "content.md"
    source.write_text("No citations here.\n")
    lookup = Mock(side_effect=AssertionError("unexpected lookup"))
    monkeypatch.setattr(zotero, "urlopen", lookup)
    continuous.run_pandoc(str(source), str(tmp_path / "content.html"))
    lookup.assert_not_called()


@pytest.mark.parametrize(
    "metadata,files",
    [
        ("", []),
        ("", ["one.bib", "two.bib"]),
        ("bibliography: [one.bib, two.bib]", ["one.bib", "two.bib"]),
        ("bibliography: refs.json", ["refs.json"]),
    ],
)
def test_no_single_bib_target_keeps_preview_without_lookup(
    tmp_path, monkeypatch, metadata, files
):
    for name in files:
        (tmp_path / name).write_text(
            "[]" if name.endswith("json") else "% empty\n"
        )
    source = tmp_path / "content.md"
    source.write_text(f"---\ntitle: Test\n{metadata}\n---\n[@missing]\n")
    before = {name: (tmp_path / name).read_bytes() for name in files}
    lookup = Mock(side_effect=AssertionError("unexpected Zotero lookup"))
    monkeypatch.setattr(zotero, "urlopen", lookup)
    html = tmp_path / "content.html"
    continuous.run_pandoc(str(source), str(html))
    assert html.is_file()
    lookup.assert_not_called()
    assert before == {name: (tmp_path / name).read_bytes() for name in files}


DUPLICATED = (
    # from RM_ESR: references.bib held budil1996nonlinear twice, so cpb
    # silently skipped adding citations that Zotero does have
    "@article{budil1996nonlinear,\n  title = {Nonlinear-least-squares},\n"
    "  volume = {120}\n}\n\n"
    "@book{kept,title={Kept}}\n\n"
    "@article{budil1996nonlinear,\n  title = {Nonlinear-Least-Squares},\n"
    "  year = 1996\n}\n"
)


@pytest.mark.parametrize(
    "decision, entry",
    [
        (
            {"action": "existing"},
            "@article{budil1996nonlinear,\n  title = {Nonlinear-least-"
            "squares},\n  volume = {120}\n}",
        ),
        (
            {"action": "incoming"},
            "@article{budil1996nonlinear,\n  title = {Nonlinear-Least-"
            "Squares},\n  year = 1996\n}",
        ),
        (
            {
                "action": "merge",
                "key": "budil1996nonlinear",
                "kind": "article",
                "fields": {
                    "title": "{Nonlinear-Least-Squares}",
                    "volume": "{120}",
                    "year": "1996",
                },
            },
            "@article{budil1996nonlinear,\n  title = {Nonlinear-Least-"
            "Squares},\n  volume = {120},\n  year = 1996\n}",
        ),
    ],
)
def test_duplicate_key_in_bibliography_is_reviewed_then_recovered(
    monkeypatch, bibliography, local_api, notices, decision, entry
):
    bibliography.write_text(DUPLICATED)
    reviews = []

    def review(matches, incoming, source, mode="zotero"):
        reviews.append((matches, incoming, source, mode))
        return {"existing_key": matches[0]["key"], **decision}

    monkeypatch.setattr(zotero, "review_duplicate", review)

    assert recover_bibliography(bibliography, ["Hoult1976SigRatNuc"]) == [
        "Hoult1976SigRatNuc"
    ]

    ((matches, incoming, source, mode),) = reviews
    assert mode == "bibliography" and source == "references.bib"
    assert matches[0]["fields"]["volume"] == "{120}"
    assert incoming["fields"]["year"] == "1996"
    text = bibliography.read_text()
    # one entry is left, where the first one was, and nothing else moves
    assert text.startswith(entry + "\n\n@book{kept,title={Kept}}\n")
    assert text.count("budil1996nonlinear") == 1
    assert "@article{Hoult1976SigRatNuc," in text
    assert notices == []


def test_duplicate_key_left_in_bibliography_is_reported(
    monkeypatch, bibliography, local_api, notices
):
    bibliography.write_text(DUPLICATED)
    original = bibliography.read_bytes()
    monkeypatch.setattr(
        zotero,
        "review_duplicate",
        lambda *_args, **_kwargs: {"action": "skip"},
    )

    assert recover_bibliography(bibliography, ["Hoult1976SigRatNuc"]) == []

    assert bibliography.read_bytes() == original
    (notice,) = notices
    assert "Hoult1976SigRatNuc" in notice
    assert "duplicate BibTeX key budil1996nonlinear" in notice
    assert "Choose one of the two entries" in notice


def test_citations_zotero_lacks_are_reported(
    bibliography, local_api, notices
):
    keys = ["Hoult1976SigRatNuc", "Guinness2024SepDetCha"]

    assert recover_bibliography(bibliography, keys) == keys[:1]

    (notice,) = notices
    assert notice.startswith("I added Hoult1976SigRatNuc from Zotero")
    assert "still missing: Guinness2024SepDetCha" in notice


def test_citations_already_present_need_no_notice(
    bibliography, local_api, notices
):
    assert recover_bibliography(bibliography, ["old"]) == []
    assert notices == []
