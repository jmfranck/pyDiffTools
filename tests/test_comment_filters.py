"""Recognize distributed Lua versions and manage project-local copies."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pydifftools import continuous


@pytest.fixture
def comment_project(tmp_path, monkeypatch):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\n<comment>A note</comment>\n")
    html = tmp_path / "notes.html"
    commands = []

    def render(command, **_kwargs):
        assert command[0] == "pandoc", "Unexpected unstubbed dialog"
        commands.append(command)
        html.write_text("<html><head></head><body>notes</body></html>")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(continuous.subprocess, "run", render)
    monkeypatch.setattr(continuous.shutil, "which", lambda _name: "tool")
    return SimpleNamespace(
        directory=tmp_path, source=source, html=html, commands=commands,
        filter=tmp_path / "comment_tags.lua",
        approval=tmp_path / ".pydifft-comment-filter.json",
        package=Path(continuous.__file__).resolve().parent,
    )


def test_history_hashes_match_committed_filter_contents():
    package = Path(continuous.__file__).resolve().parent
    history = json.loads((package / "comment_filter_history.json").read_text())
    modes = {entry["mode"] for entry in history["comment_tags.lua"].values()}
    assert modes == {
        "default", "margin", "none",
    }
    for versions in history.values():
        for digest, entry in versions.items():
            result = continuous._comment_filter_git(
                package.parent, "show", entry["commit"] + ":" + entry["path"]
            )
            assert result.returncode == 0, result.stderr
            content = result.stdout.replace("\r\n", "\n").replace("\r", "\n")
            assert hashlib.sha256(content.encode()).hexdigest() == digest


@pytest.mark.parametrize("mode", ["default", "margin", "none"])
def test_current_and_historical_modes_accept_windows_line_endings(
    comment_project, mode
):
    project = comment_project
    names = {
        "default": "comment_tags.lua", "margin": "comment_tags_margin.lua",
        "none": "comment_tags_no_comments.lua",
    }
    content = (project.package / names[mode]).read_text()
    project.filter.write_bytes(content.replace("\n", "\r\n").encode())
    assert continuous._comment_filter_mode(project.filter) == mode
    history = json.loads(
        (project.package / "comment_filter_history.json").read_text()
    )
    entry = next(
        entry for digest, entry in history["comment_tags.lua"].items()
        if entry["mode"] == mode
        and digest != continuous._comment_filter_digest(project.filter)
    )
    result = continuous._comment_filter_git(
        project.package.parent, "show", entry["commit"] + ":" + entry["path"]
    )
    assert result.returncode == 0
    project.filter.write_bytes(result.stdout.replace("\n", "\r\n").encode())
    expected = "outdated" if mode == "default" else "outdated-" + mode
    assert continuous._comment_filter_mode(project.filter) == expected


@pytest.mark.parametrize("manage", [True, False])
@pytest.mark.parametrize("mode", ["default", "none"])
def test_tracked_filter_requires_explicit_choice_to_keep_tracking(
    comment_project, monkeypatch, manage, mode
):
    project = comment_project
    name = "comment_tags.lua" if mode == "default" else (
        "comment_tags_no_comments.lua"
    )
    project.filter.write_bytes(
        (project.package / name).read_bytes()
    )
    unrelated = project.directory / "other.lua"
    unrelated.write_text("-- A separate project filter\n")
    for arguments in (
        ("init", "-q"), ("add", "."),
        ("-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-qm", "Project filters"),
    ):
        result = continuous._comment_filter_git(project.directory, *arguments)
        assert result.returncode == 0, result.stderr
    prompts = []

    def choose(mode):
        prompts.append(mode)
        return manage

    monkeypatch.setattr(continuous, "confirm_restore_comment_filter", choose)
    continuous.run_pandoc(
        str(project.source), str(project.html), no_comments=mode == "none"
    )
    assert prompts == ["tracked"]
    tracked = continuous._comment_filter_git(project.directory, "ls-files")
    assert ("comment_tags.lua" in tracked.stdout.splitlines()) is not manage
    assert "other.lua" in tracked.stdout.splitlines()
    assert project.filter.exists()
    ignore = (project.directory / ".gitignore").read_text().splitlines()
    assert ("/comment_tags.lua" in ignore) is manage
    if not manage:
        approval = json.loads(project.approval.read_text())
        assert approval["keep_tracked"] is True
        continuous.run_pandoc(
            str(project.source), str(project.html), no_comments=mode == "none"
        )
        assert prompts == ["tracked"]
        if mode == "none":
            manage = True
            continuous.run_pandoc(str(project.source), str(project.html))
            assert prompts == ["tracked", "none"]
            tracked = continuous._comment_filter_git(
                project.directory, "ls-files"
            )
            assert "comment_tags.lua" not in tracked.stdout.splitlines()
            assert not project.approval.exists()
            assert continuous._comment_filter_mode(project.filter) == "default"


@pytest.mark.parametrize("name, mode", [
    ("comment_tags.lua", "default"), ("comment_tags.lua", "margin"),
    ("comment_tags.lua", "none"), ("comments.css", "shared"),
    ("comment_toggle.js", "shared"),
])
def test_known_old_helpers_offer_update_even_with_current_lua(
    comment_project, monkeypatch, name, mode
):
    project = comment_project
    project.filter.write_text(
        (project.package / "comment_tags.lua").read_text()
    )
    current_names = {
        "default": "comment_tags.lua", "margin": "comment_tags_margin.lua",
        "none": "comment_tags_no_comments.lua", "shared": name,
    }
    current_path = project.package / current_names[mode]
    history = json.loads(
        (project.package / "comment_filter_history.json").read_text()
    )
    entry = next(
        entry for digest, entry in history[name].items()
        if entry["mode"] == mode
        and digest != continuous._comment_filter_digest(current_path)
    )
    result = continuous._comment_filter_git(
        project.package.parent, "show", entry["commit"] + ":" + entry["path"]
    )
    assert result.returncode == 0
    local = project.directory / name
    local.write_text(result.stdout)
    if name != "comment_tags.lua":
        project.filter.unlink()
        project.source.write_text("# Notes without comment markup\n")
    prompts = []

    def update(reason):
        prompts.append(reason)
        return True

    monkeypatch.setattr(continuous, "confirm_restore_comment_filter", update)
    continuous.run_pandoc(
        str(project.source), str(project.html), no_comments=mode == "none",
        comments_to_margin=mode == "margin",
    )
    assert prompts == ["outdated"]
    assert local.read_text() == current_path.read_text()
    assert not project.approval.exists()


@pytest.mark.parametrize("name", [
    "comment_tags.lua", "comments.css", "comments_author_colors.css",
    "comment_toggle.js",
])
def test_local_edits_require_approval_again_when_contents_change(
    comment_project, monkeypatch, name
):
    project = comment_project
    project.filter.write_text(
        (project.package / "comment_tags.lua").read_text()
    )
    local = project.directory / name
    original = (project.package / name).read_text() + "\nlocal customization\n"
    local.write_text(original)
    prompts = []

    def keep(reason):
        prompts.append(reason)
        return False

    monkeypatch.setattr(continuous, "confirm_restore_comment_filter", keep)
    continuous.run_pandoc(str(project.source), str(project.html))
    assert prompts == ["custom"]
    assert local.read_text() == original
    approval = json.loads(project.approval.read_text())
    assert set(approval) == {"files", "keep_tracked"}
    assert approval["files"][name] == continuous._comment_filter_digest(local)
    continuous.run_pandoc(str(project.source), str(project.html))
    assert prompts == ["custom"]
    local.write_text(original + "another edit\n")
    continuous.run_pandoc(str(project.source), str(project.html))
    assert prompts == ["custom", "custom"]


def test_cancelled_choice_leaves_local_helpers_and_no_approval(
    comment_project, monkeypatch
):
    project = comment_project
    project.filter.write_text("-- locally edited Lua\n")
    monkeypatch.setattr(
        continuous, "confirm_restore_comment_filter", lambda _reason: None
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        continuous.run_pandoc(str(project.source), str(project.html))
    assert project.filter.read_text() == "-- locally edited Lua\n"
    assert not project.approval.exists()
    assert not (project.directory / ".gitignore").exists()
    assert not project.commands


def test_legacy_inactive_custom_filter_is_preserved_during_migration(
    comment_project, monkeypatch
):
    project = comment_project
    project.filter.write_text(
        (project.package / "comment_tags_no_comments.lua").read_text()
    )
    legacy = project.directory / "comment_tags.lua.inactive"
    legacy.write_text("-- custom legacy filter\n")
    monkeypatch.setattr(
        continuous, "confirm_restore_comment_filter", lambda _reason: True
    )
    continuous.run_pandoc(str(project.source), str(project.html))
    assert not legacy.exists()
    backups = list(project.directory.glob(".pydifft-comment-filter-backup.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "-- custom legacy filter\n"
    assert project.filter.read_text() == (
        project.package / "comment_tags.lua"
    ).read_text()


def test_previous_session_state_cannot_override_on_disk_mode(
    comment_project, monkeypatch
):
    project = comment_project
    project.filter.write_text(
        (project.package / "comment_tags.lua").read_text()
    )
    project.approval.write_text(json.dumps({
        "last_filter_sha256": continuous._comment_filter_digest(
            project.package / "comment_tags_no_comments.lua"
        ),
    }))

    def unexpected_prompt(_reason):
        raise AssertionError("The on-disk filter already shows comments")

    monkeypatch.setattr(
        continuous, "confirm_restore_comment_filter", unexpected_prompt
    )
    continuous.run_pandoc(str(project.source), str(project.html))
    assert continuous._comment_filter_mode(project.filter) == "default"


@pytest.mark.parametrize("keep, expected", [(True, False), (False, True)])
def test_real_dialog_requires_confirmation_before_keeping_local_files(
    monkeypatch, keep, expected
):
    real_run = subprocess.run

    def drive_dialog(command, **kwargs):
        # Click through the actual Qt dialogs, including rejecting the second
        # confirmation and returning to the default update choice.
        command = list(command)
        automation = """
from PySide6.QtCore import QTimer
steps = ["keep current helper files", CHOICE, FINAL]
def interact():
    for widget in app.topLevelWidgets():
        if isinstance(widget, QMessageBox) and widget.isVisible():
            if widget.windowTitle() == "Keep this comment filter?":
                assert widget.defaultButton().text() == "go back"
            elif len(steps) == 3:
                assert widget.defaultButton().text().startswith("update")
            for button in widget.buttons():
                if steps and button.text() == steps[0]:
                    steps.pop(0)
                    button.click()
                    return
timer = QTimer()
timer.timeout.connect(interact)
timer.start(10)
QTimer.singleShot(5000, lambda: sys.exit(99))
""".replace(
            "CHOICE", repr("keep local helpers and stop asking" if keep
                           else "go back")
        ).replace(
            "FINAL", repr("update filter and styles; untrack and ignore")
        )
        command[2] = command[2].replace(
            "app = QApplication(sys.argv[:1])",
            "app = QApplication(sys.argv[:1])\n" + automation,
        )
        return real_run(command, **kwargs)

    monkeypatch.setattr(continuous.subprocess, "run", drive_dialog)
    assert continuous.confirm_restore_comment_filter("custom") is expected


def test_no_comments_dialog_escape_cancels_instead_of_selecting_keep(
    monkeypatch
):
    real_run = subprocess.run

    def close_dialog(command, **kwargs):
        command = list(command)
        command[2] = command[2].replace(
            "box.exec()",
            "__import__('PySide6.QtCore', fromlist=['QTimer']).QTimer."
            "singleShot(10, box.close)\n    box.exec()",
        )
        return real_run(command, **kwargs)

    monkeypatch.setattr(continuous.subprocess, "run", close_dialog)
    assert continuous.confirm_restore_comment_filter("none") is None


def test_catalog_includes_renamed_files_and_merged_branch_versions(tmp_path):
    package = Path(continuous.__file__).resolve().parent
    script = tmp_path / ".github/scripts/update_comment_filter_history.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        (package.parent / ".github/scripts" / script.name).read_text()
    )
    filters = tmp_path / "pydifftools"
    filters.mkdir()
    original = tmp_path / "comment_tags.lua"
    original.write_text("-- initial comments\n")
    for name, content in {
        "comment_tags_margin.lua": "-- margin\n",
        "comment_tags_no_comments.lua": "-- no comments\n",
        "comments.css": "/* original styles */\n",
        "comments_author_colors.css": "/* colors */\n",
        "comment_toggle.js": "// toggling\n",
    }.items():
        (filters / name).write_text(content)
    for arguments in (
        ("init", "-qb", "main"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.com"),
        ("add", "."), ("commit", "-qm", "Initial helpers"),
        ("checkout", "-qb", "old-release"),
    ):
        result = continuous._comment_filter_git(tmp_path, *arguments)
        assert result.returncode == 0, result.stderr
    original.write_text("-- branch comment version\n")
    for arguments in (
        ("commit", "-qam", "Old branch helpers"),
        ("checkout", "-q", "main"),
        ("mv", "comment_tags.lua", "pydifftools/comment_tags.lua"),
        ("commit", "-qm", "Package helpers"),
        ("merge", "-q", "-s", "ours", "old-release", "-m", "Merge history"),
        ("branch", "-D", "old-release"),
    ):
        result = continuous._comment_filter_git(tmp_path, *arguments)
        assert result.returncode == 0, result.stderr
    (filters / "comment_tags.lua").write_text("-- current comments\n")
    (filters / "comments.css").write_text("/* current styles */\n")
    result = continuous._comment_filter_git(
        tmp_path, "commit", "-qam", "Current helpers"
    )
    assert result.returncode == 0, result.stderr
    subprocess.run(
        [sys.executable, str(script)], check=True, capture_output=True
    )
    history = json.loads((filters / "comment_filter_history.json").read_text())
    for content in (
        "-- initial comments\n", "-- branch comment version\n",
        "-- current comments\n",
    ):
        digest = hashlib.sha256(content.encode()).hexdigest()
        assert history["comment_tags.lua"][digest]["mode"] == "default"
    assert len(history["comments.css"]) == 2


def test_kept_old_filter_only_prompts_once_per_watch_session(
    comment_project, monkeypatch
):
    project = comment_project
    history = json.loads(
        (project.package / "comment_filter_history.json").read_text()
    )
    entry = next(
        entry for digest, entry in history["comment_tags.lua"].items()
        if entry["mode"] == "default"
        and digest != continuous._comment_filter_digest(
            project.package / "comment_tags.lua"
        )
    )
    content = continuous._comment_filter_git(
        project.package.parent, "show", entry["commit"] + ":" + entry["path"]
    ).stdout
    project.filter.write_text(content)
    prompts = []

    def keep(reason):
        prompts.append(reason)
        return False

    monkeypatch.setattr(continuous, "confirm_restore_comment_filter", keep)
    session = {}
    for _ in range(2):
        continuous.run_pandoc(
            str(project.source), str(project.html),
            comment_filter_session=session,
        )
    assert prompts == ["outdated"]
    assert not project.approval.exists()
    continuous.run_pandoc(str(project.source), str(project.html))
    assert prompts == ["outdated", "outdated"]
