import shutil
import subprocess
from zipfile import ZipFile

from lxml import etree
import pytest

from pydifftools.word_export import W, compare, word_export


def test_comparison_keeps_only_target_comments(tmp_path):
    part = "word/document.xml"
    baseline, clean, tracked = (
        tmp_path / name for name in ("old.docx", "new.docx", "tracked.docx")
    )
    for path, text in ((baseline, "old"), (clean, "new")):
        root = etree.Element(W + "document")
        para = etree.SubElement(etree.SubElement(root, W + "body"), W + "p")
        etree.SubElement(para, W + "commentRangeStart", {W + "id": text})
        etree.SubElement(etree.SubElement(para, W + "r"), W + "t").text = text
        etree.SubElement(para, W + "commentRangeEnd", {W + "id": text})
        with ZipFile(path, "w") as archive:
            archive.writestr(part, etree.tostring(root))
            archive.writestr("word/comments.xml", text)

    compare(baseline, clean, tracked, "2026-11-18T00:00:00Z")
    with ZipFile(tracked) as archive:
        root = etree.fromstring(archive.read(part))
        assert archive.read("word/comments.xml") == b"new"
    assert [
        node.get(W + "id") for node in root.iter(W + "commentRangeStart")
    ] == ["new"]
    assert root.find(".//" + W + "delText").text == "old"
    assert root.find(".//" + W + "ins//" + W + "t").text == "new"


def test_inline_math_conversion_keeps_adjacent_prose(tmp_path):
    math = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    part = "word/document.xml"
    baseline, clean, tracked = (
        tmp_path / name for name in ("old.docx", "new.docx", "tracked.docx")
    )
    phrases = (
        ("dielectric constant (", "T"),
        ("protein dipole fluctuations (", "P"),
        ("water dipole fluctuation (", "W"),
        ("protein-water cross correlation (", "PW"),
    )
    for path in (baseline, clean):
        root = etree.Element(W + "document")
        para = etree.SubElement(etree.SubElement(root, W + "body"), W + "p")
        for phrase, subscript in phrases:
            prefix = etree.SubElement(para, W + "r")
            etree.SubElement(prefix, W + "t").text = (
                phrase + "ε" if path == baseline else phrase
            )
            if path == baseline:
                run = etree.SubElement(para, W + "r")
                props = etree.SubElement(run, W + "rPr")
                etree.SubElement(
                    props, W + "vertAlign", {W + "val": "subscript"},
                )
                etree.SubElement(run, W + "t").text = subscript
            else:
                equation = etree.SubElement(para, math + "oMath")
                run = etree.SubElement(equation, math + "r")
                etree.SubElement(run, math + "t").text = "ε" + subscript
            etree.SubElement(
                etree.SubElement(para, W + "r"), W + "t",
            ).text = ") "
        with ZipFile(path, "w") as archive:
            archive.writestr(part, etree.tostring(root))

    compare(baseline, clean, tracked, "2026-11-18T00:00:00Z")
    with ZipFile(tracked) as archive:
        root = etree.fromstring(archive.read(part))
    assert [node.text for node in root.iter(W + "delText")] == [
        token for _, subscript in phrases for token in ("ε", subscript)
    ]
    inserted = list(root.iter(W + "ins"))
    assert [
        node.findtext(".//" + math + "t") for node in inserted
    ] == ["ε" + subscript for _, subscript in phrases]
    assert not any(node.find(".//" + W + "t") is not None for node in inserted)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="requires Pandoc")
def test_word_export_requires_commit_and_names_clean_copy(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=tmp_path, text=True, stderr=subprocess.PIPE,
        ).strip()

    git("init")
    git("config", "user.name", "Reviewer")
    git("config", "user.email", "reviewer@example.com")
    git("config", "commit.gpgsign", "false")
    source = tmp_path / "paper draft.md"
    baseline = tmp_path / "baseline.md"
    baseline.write_text("Old text.\n")
    (tmp_path / "word.yaml").write_text("filters: []\n")
    source.write_text("---\ndocx-defaults: word.yaml\n---\n\nCurrent text.\n")
    for staged in (False, True):
        if staged:
            git("add", source.name)
        with pytest.raises(SystemExit, match="Commit the Markdown file first"):
            word_export(source, baseline=baseline)
        assert not list(tmp_path.glob("*.docx"))

    git("commit", "-m", "Save manuscript")
    assert word_export(source)
    commit = git("rev-parse", "--short=8", "HEAD")
    assert (tmp_path / f"paper draft-{commit}.docx").is_file()
    assert not (tmp_path / "paper draft-tracked.docx").exists()
    assert word_export(source, baseline=baseline)
    assert (tmp_path / f"paper draft-{commit}.docx").is_file()
    assert (tmp_path / "paper draft-tracked.docx").is_file()
    source.write_text(source.read_text() + "\nUncommitted edit.\n")
    with pytest.raises(SystemExit, match="has uncommitted changes"):
        word_export(source, baseline=baseline)
    assert word_export(source)
    assert (tmp_path / f"paper draft-{commit}-dirty.docx").is_file()

    baseline.write_text(
        "Current\n<JFcom>Resolved comment</JFcom>\ntext.\n"
    )
    source.write_text(
        "---\ndocx-defaults: word.yaml\n---\n\nCurrent text.\n\n"
        "<JFcom>New comment</JFcom>\n"
    )
    git("add", source.name)
    git("commit", "-m", "Update manuscript comments")
    baseline.write_text(
        "---\ndocx-defaults: word.yaml\n---\n\n" + baseline.read_text()
    )
    assert word_export(source, baseline=baseline)
    with ZipFile(tmp_path / "paper draft-tracked.docx") as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        assert b"New comment" not in archive.read("word/document.xml")
        assert b"Resolved" not in archive.read("word/comments.xml")
    assert not list(root.iter(W + "ins"))
    assert not list(root.iter(W + "del"))
    assert len(list(root.iter(W + "commentReference"))) == 1


@pytest.mark.parametrize("split", [True, False])
def test_paragraph_break_keeps_shared_prose(tmp_path, split):
    part = "word/document.xml"
    baseline, clean, tracked = (
        tmp_path / name for name in ("old.docx", "new.docx", "tracked.docx")
    )
    joined = ["First paragraph still here.", "Before break. After break."]
    divided = [
        "First paragraph still here!", "Before break.", "After break.",
    ]
    for path, paragraphs in zip(
        (baseline, clean), (joined, divided) if split else (divided, joined),
    ):
        root = etree.Element(W + "document")
        body = etree.SubElement(root, W + "body")
        for content in paragraphs:
            p = etree.SubElement(body, W + "p")
            etree.SubElement(etree.SubElement(p, W + "r"), W + "t").text = (
                content
            )
        if path == clean:
            p = etree.SubElement(body, W + "p")
            etree.SubElement(p, W + "commentRangeStart", {W + "id": "0"})
            etree.SubElement(p, W + "commentRangeEnd", {W + "id": "0"})
        with ZipFile(path, "w") as archive:
            archive.writestr(part, etree.tostring(root))

    compare(baseline, clean, tracked, "2026-11-18T00:00:00Z")
    with ZipFile(tracked) as archive:
        root = etree.fromstring(archive.read(part))
    removed = {node.text for node in root.iter(W + "delText")}
    inserted = [
        node.findtext(".//" + W + "t") for node in root.iter(W + "ins")
    ]
    if split:
        assert removed == {".", " "}
        assert inserted == ["!", None]
    else:
        assert removed == {"!"}
        assert inserted == [".", " "]
        assert len(list(root.iterfind(
            ".//" + W + "pPr/" + W + "rPr/" + W + "del"
        ))) == 1
    assert len(list(root.iter(W + "commentRangeStart"))) == 1


def test_run_formatting_revision_requires_a_style_change(tmp_path):
    part = "word/document.xml"
    baseline, clean, tracked = (
        tmp_path / name for name in ("old.docx", "new.docx", "tracked.docx")
    )
    for path in (baseline, clean):
        root = etree.Element(W + "document")
        para = etree.SubElement(etree.SubElement(root, W + "body"), W + "p")
        for content in ("same", " anchor ", "bold"):
            run = etree.SubElement(para, W + "r")
            if path == baseline and content == "same":
                etree.SubElement(run, W + "rPr")
            if path == clean and content == "bold":
                etree.SubElement(etree.SubElement(run, W + "rPr"), W + "b")
            etree.SubElement(run, W + "t").text = content
        with ZipFile(path, "w") as archive:
            archive.writestr(part, etree.tostring(root))

    compare(baseline, clean, tracked, "2026-11-18T00:00:00Z")
    with ZipFile(tracked) as archive:
        root = etree.fromstring(archive.read(part))
    assert [
        node.getparent().getparent().findtext(W + "t")
        for node in root.iter(W + "rPrChange")
    ] == ["bold"]
    assert not list(root.iter(W + "ins"))
    assert not list(root.iter(W + "del"))
