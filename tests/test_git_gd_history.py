import os
import subprocess

import pytest

from pydifftools.git_gd import main, numstat_for_paths


def test_history_merge_lanes_refs_and_old_commits(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pydifftools.git_gd_history import load_history

    monkeypatch.chdir(tmp_path)

    def git(*args, old=False):
        env = dict(os.environ)
        if old:
            env.update(GIT_AUTHOR_DATE="2000-01-01T12:00:00+00:00",
                       GIT_COMMITTER_DATE="2000-01-01T12:00:00+00:00")
        return subprocess.check_output(
            ["git", *args], env=env, text=True
        ).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("commit", "--allow-empty", "-m", "old", old=True)
    old = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "fork")
    fork = git("rev-parse", "HEAD")
    git("checkout", "-b", "topic")
    git("commit", "--allow-empty", "-m", "topic work")
    topic = git("rev-parse", "HEAD")
    git("tag", "-a", "release", "-m", "release")
    git("checkout", "main")
    git("commit", "--allow-empty", "-m", "main work")
    main = git("rev-parse", "HEAD")
    git("merge", "--no-ff", "topic", "-m", "merge topic")
    merge = git("rev-parse", "HEAD")
    commits = load_history()
    by_oid = {commit.oid: commit for commit in commits}
    assert old in by_oid
    assert by_oid[old].date == "2000-01-01T12:00:00+00:00"
    assert by_oid[old].author == "Test"
    assert by_oid[merge].parents == [main, topic]
    assert by_oid[merge].lane == by_oid[main].lane == by_oid[fork].lane
    assert by_oid[topic].lane != by_oid[merge].lane
    assert by_oid[topic].label == "release"
    assert by_oid[merge].label == "main"
    expected = git("log", "--all", "--date-order",
                   "--max-count=40", "--format=%H").splitlines()
    assert [commit.oid for commit in commits] == expected


@pytest.mark.parametrize("total", [80, 85])
def test_history_pagination_across_branches(tmp_path, monkeypatch, total):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2000-01-01T12:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2000-01-01T12:00:00+00:00")
    monkeypatch.chdir(tmp_path)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pydifftools.git_gd_history import (
        CommitBubble, HistoryWindow, load_history,
    )

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    for index in range(total):
        if index == 55:
            git("checkout", "-b", "topic", "HEAD~30")
        git("commit", "--allow-empty", "-m", f"commit {index}")
    git("checkout", "main")
    expected = git("log", "--all", "--date-order", "--format=%H").splitlines()
    app = QApplication.instance() or QApplication([])
    window = HistoryWindow("repo", load_history())
    window.show()
    app.processEvents()
    assert [commit.oid for commit in window.commits] == expected[:40]
    assert window.more_button.arrowType() == Qt.ArrowType.DownArrow
    endpoint = window.commits[0]
    window.set_endpoint(endpoint)
    window.view.verticalScrollBar().setValue(300)
    scroll = window.view.verticalScrollBar().value()
    for count in (80, total):
        assert window.more_button.isEnabled()
        QTest.mouseClick(window.more_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert [commit.oid for commit in window.commits] == expected[:count]
        bubbles = [item for item in window.scene.items()
                   if isinstance(item, CommitBubble)]
        assert len(bubbles) == count
        assert window.endpoint is endpoint
        assert window.view.verticalScrollBar().value() == scroll
        by_oid = {commit.oid: commit for commit in window.commits}
        for commit in window.commits:
            if commit.parents and commit.parents[0] in by_oid:
                assert commit.lane == by_oid[commit.parents[0]].lane or (
                    commit.subject == "commit 55"
                )
    assert not window.more_button.isEnabled()
    window.close()


def test_history_clicks_and_endpoint(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pydifftools import git_gd_history as history

    app = QApplication.instance() or QApplication([])
    first = history.HistoryCommit("a" * 40, [], "2026-09-17", "first")
    second = history.HistoryCommit(
        "b" * 40, [first.oid], "2026-09-18", "second", tags=["v1"]
    )
    calls = []
    monkeypatch.setattr(
        history, "build_entries",
        lambda args: (calls.append(args) or args, []),
    )
    window = history.HistoryWindow("repo", [second, first])
    window.show()
    app.processEvents()
    bubble = next(item for item in window.scene.items()
                  if isinstance(item, history.CommitBubble)
                  and item.commit is first)
    assert first.oid in bubble.toolTip()
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.view.mapFromScene(bubble.scenePos()))
    assert calls[-1] == [first.oid]
    assert window.diff_windows[-1].windowTitle() == "gd aaaaaa"
    # Messages and badge labels survive construction and open the same view.
    for label in ("first", "v1"):
        text = next(item for item in window.text_items
                    if item.toPlainText() == label)
        QTest.mouseClick(
            window.view.viewport(), Qt.MouseButton.LeftButton,
            pos=window.view.mapFromScene(text.sceneBoundingRect().center()),
        )
        assert calls[-1] == [first.oid if label == "first" else second.oid]
    window.set_endpoint(second)
    window.open_commit(first)
    assert calls[-1] == [first.oid, second.oid]
    assert window.diff_windows[-1].windowTitle() == "gd aaaaaa v1"
    window.set_endpoint(None)
    window.open_commit(second)
    assert calls[-1] == [second.oid]
    assert window.diff_windows[-1].windowTitle() == "gd v1"
    for diff in window.diff_windows:
        diff.close()
    window.close()


def test_tree_launches_history(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pydifftools import command_line, git_gd, git_gd_history

    from PySide6.QtWidgets import QApplication
    from unittest.mock import Mock

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(git_gd, "repo_name", lambda: "repo")
    monkeypatch.setattr(git_gd_history, "load_history", lambda: [])
    window = Mock()
    factory = Mock(return_value=window)
    monkeypatch.setattr(git_gd_history, "HistoryWindow", factory)
    command_line.main(["tree"])
    factory.assert_called_once_with("repo", [])
    window.show.assert_called_once()
    assert app is not None


@pytest.mark.parametrize("args", [[], ["HEAD"]])
def test_gd_launches_review(monkeypatch, args):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pydifftools import git_gd, git_gd_qt

    monkeypatch.setattr(git_gd, "repo_name", lambda: "repo")
    monkeypatch.setattr(git_gd, "build_entries", lambda args: (args, []))
    calls = []
    monkeypatch.setattr(
        git_gd_qt, "launch_review",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    assert main(args) == 0
    assert calls == [(("repo", args, []), {"command_args": args})]


def test_numstat_handles_multiple_paths(monkeypatch):
    from pydifftools import git_gd

    calls = []
    monkeypatch.setattr(git_gd, "git_bytes",
                        lambda args: calls.append(args) or b"2\t1\tx\0")
    assert numstat_for_paths(["a", "b"], ["old", "new"]) == (2, 1)
    assert calls[-1][-3:] == ["--", "old", "new"]
    monkeypatch.setattr(git_gd, "git_bytes", lambda args: b"-\t-\tx\0")
    assert numstat_for_paths(["a", "b"], ["image"]) == (None, None)
