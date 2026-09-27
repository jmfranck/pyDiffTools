import pytest

from pydifftools import comment_migration
from pydifftools.comment_migration import (
    _migration_dialog,
    _most_distant_hue,
)


def test_hue_picker_starts_at_seed_and_fills_largest_hue_gap():
    assert _most_distant_hue([]) == pytest.approx(214.5454545)
    assert _most_distant_hue(["#ff0000"]) == pytest.approx(180)
    assert _most_distant_hue(["#ff0000", "#00ff00"]) == pytest.approx(240)


def test_migration_dialog_builds_qt_script_and_decodes_result(monkeypatch):
    captured = {}

    def fake_run(command, **_kwargs):
        captured["script"] = command[2]
        compile(command[2], "<comment migration dialog>", "exec")
        return type(
            "Completed",
            (),
            {"returncode": 0, "stderr": "", "stdout": '{"accepted": true}'},
        )()

    monkeypatch.setattr(comment_migration.subprocess, "run", fake_run)

    result = _migration_dialog("<ABcom>note</ABcom>", {}, False)

    assert result == {"accepted": True}
    assert "QColor.fromHsv" in captured["script"]
    assert "QComboBox" in captured["script"]


def test_prepare_migrates_legacy_tags_and_div_classes(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    path.write_text(
        "---\ntitle: Notes\nJFcolor: '#5aa0ff'\n---\n"
        "<comment>old</comment>\n\n::: {.comment-left}\nblock\n:::\n"
    )
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {
            "accepted": True,
            "replacements": {"legacy": "JF"},
            "colors": {},
        },
    )

    updated = comment_migration.prepare_comment_source(str(path))

    assert "<JFcom>old</JFcom>" in updated
    assert "{.JFcom-left}" in updated
    assert "JFcolor: '#5aa0ff'" in updated


def test_prepare_creates_yaml_header_and_maps_unknown_author(
    tmp_path, monkeypatch
):
    path = tmp_path / "notes.md"
    path.write_text("<ABcom-right>text</ABcom-right>\n")
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {
            "accepted": True,
            "replacements": {},
            "colors": {"AB": "#9bff5a"},
        },
    )

    updated = comment_migration.prepare_comment_source(str(path))

    assert updated.startswith('---\nABcolor: "#9bff5a"\n---\n')
    assert "<ABcom-right>text</ABcom-right>" in updated


def test_prepare_adds_color_to_existing_yaml_header(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    source = "---\ntitle: Notes\n---\n<ABcom>text</ABcom>\n"
    path.write_text(source)
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {
            "accepted": True,
            "replacements": {},
            "colors": {"AB": "#c65aff"},
        },
    )

    updated = comment_migration.prepare_comment_source(str(path))

    assert updated.startswith(
        '---\ntitle: Notes\nABcolor: "#c65aff"\n---\n'
    )
    assert "<ABcom>text</ABcom>" in updated


def test_prepare_preserves_windows_line_endings(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    source = (
        "---\r\ntitle: Notes\r\n---\r\n"
        "<ABcom>text</ABcom>\r\n"
    )
    path.write_bytes(source.encode("utf-8"))
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {
            "accepted": True,
            "replacements": {},
            "colors": {"AB": "#c65aff"},
        },
    )

    updated = comment_migration.prepare_comment_source(str(path))

    assert "\r\n" in updated
    assert "\n" not in updated.replace("\r\n", "")


def test_prepare_maps_unknown_tags_to_existing_user(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    path.write_text(
        "---\nJFcolor: '#5aa0ff'\n---\n<ABcom>text</ABcom>\n"
    )
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {
            "accepted": True,
            "replacements": {"AB": "JF"},
            "colors": {},
        },
    )

    updated = comment_migration.prepare_comment_source(str(path))

    assert "<JFcom>text</JFcom>" in updated


def test_prepare_cancel_preserves_source(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    original = "<comment>old</comment>\n"
    path.write_text(original)
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: {"accepted": False},
    )

    with pytest.raises(RuntimeError, match="was canceled"):
        comment_migration.prepare_comment_source(str(path))

    assert path.read_text() == original


def test_declared_author_does_not_open_migration_dialog(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    source = "---\nJFcolor: '#5aa0ff'\n---\n<JFcom>text</JFcom>\n"
    path.write_text(source)
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: pytest.fail(
            "fully registered author should not prompt"
        ),
    )

    assert comment_migration.prepare_comment_source(str(path)) == source


def test_invalid_color_stops_before_migration_dialog(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    path.write_text("---\nJFcolor: blue\n---\n<JFcom>text</JFcom>\n")
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: pytest.fail(
            "invalid metadata must fail before prompting"
        ),
    )

    with pytest.raises(ValueError, match="six-digit hex color"):
        comment_migration.prepare_comment_source(str(path))


def test_unclosed_front_matter_stops_before_migration_dialog(
    tmp_path, monkeypatch
):
    path = tmp_path / "notes.md"
    path.write_text("---\ntitle: Notes\n<JFcom>text</JFcom>\n")
    monkeypatch.setattr(
        comment_migration,
        "_migration_dialog",
        lambda *_args: pytest.fail(
            "unclosed front matter must fail before prompting"
        ),
    )

    with pytest.raises(ValueError, match="no closing delimiter"):
        comment_migration.prepare_comment_source(str(path))
