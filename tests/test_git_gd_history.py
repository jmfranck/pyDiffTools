import os
import subprocess

from pydifftools.git_gd import main, numstat_for_paths


def test_history_merge_lanes_refs_and_cutoff(tmp_path, monkeypatch):
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
    assert old not in by_oid
    assert by_oid[merge].parents == [main, topic]
    assert by_oid[merge].lane == by_oid[main].lane == by_oid[fork].lane
    assert by_oid[topic].lane != by_oid[merge].lane
    assert by_oid[topic].label == "release"
    assert by_oid[merge].label == "main"
    expected = git("log", "--all", "--date-order",
                   "--since-as-filter=2 weeks ago", "--format=%H").splitlines()
    assert [commit.oid for commit in commits] == expected


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


def test_no_arguments_launch_history(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pydifftools import git_gd, git_gd_history

    from PySide6.QtWidgets import QApplication
    from unittest.mock import Mock

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(git_gd, "repo_name", lambda: "repo")
    monkeypatch.setattr(git_gd_history, "load_history", lambda: [])
    window = Mock()
    factory = Mock(return_value=window)
    monkeypatch.setattr(git_gd_history, "HistoryWindow", factory)
    assert main([]) == 0
    factory.assert_called_once_with("repo", [])
    window.show.assert_called_once()
    assert app is not None


def test_explicit_arguments_keep_review(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pydifftools import git_gd, git_gd_qt

    monkeypatch.setattr(git_gd, "repo_name", lambda: "repo")
    monkeypatch.setattr(git_gd, "build_entries", lambda args: (args, []))
    calls = []
    monkeypatch.setattr(
        git_gd_qt, "launch_review",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    assert main(["HEAD"]) == 0
    assert calls == [(("repo", ["HEAD"], []), {"command_args": ["HEAD"]})]


def test_numstat_handles_multiple_paths(monkeypatch):
    from pydifftools import git_gd

    calls = []
    monkeypatch.setattr(git_gd, "git_bytes",
                        lambda args: calls.append(args) or b"2\t1\tx\0")
    assert numstat_for_paths(["a", "b"], ["old", "new"]) == (2, 1)
    assert calls[-1][-3:] == ["--", "old", "new"]
    monkeypatch.setattr(git_gd, "git_bytes", lambda args: b"-\t-\tx\0")
    assert numstat_for_paths(["a", "b"], ["image"]) == (None, None)
