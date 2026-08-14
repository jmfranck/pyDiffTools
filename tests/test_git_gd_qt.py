from pydifftools.git_gd import DiffEntry


def test_added_and_deleted_files_show_status_instead_of_delta(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_qt import DiffWindow

    app = QApplication.instance() or QApplication([])
    added = DiffEntry(path="new.png", added=None, deleted=None, status="A")
    deleted = DiffEntry(path="removed.txt", added=0, deleted=12, status="D")
    window = DiffWindow(
        "repo", [], [added, deleted], start_image_scores=False
    )

    assert window.model.data(window.model.index(0, 1)) == "A"
    assert window.model.data(window.model.index(1, 1)) == "D"
    window.close()
    assert app is not None


def test_image_scores_replace_binary_and_reorder_images(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_qt import DiffWindow

    app = QApplication.instance() or QApplication([])
    text = DiffEntry(path="notes.txt", added=2, deleted=3)
    first = DiffEntry(path="first.png", added=None, deleted=None)
    second = DiffEntry(path="second.png", added=None, deleted=None)
    window = DiffWindow(
        "repo",
        ["HEAD~"],
        [text, first, second],
        start_image_scores=False,
    )

    assert window.model.data(window.model.index(1, 1)) == "rgb … a …"
    window.table.selectRow(2)
    window.remaining_image_scores = 2
    window.results_finished(first, 12.34, 4.56, None)
    window.results_finished(second, 45.67, 8.91, None)

    assert window.model.entries == [text, second, first]
    assert window.model.data(window.model.index(1, 1)) == "rgb 45.7 a 8.9"
    assert window.model.data(window.model.index(2, 1)) == "rgb 12.3 a 4.6"
    assert window.model.entries[window.table.currentIndex().row()] is second
    window.close()
    assert app is not None


def test_image_worker_replaces_pending_score_in_window(monkeypatch):
    """Exercise the worker signal path rather than calling its callback."""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import pydifftools.git_gd_qt as git_gd_qt

    app = QApplication.instance() or QApplication([])
    image = DiffEntry(path="changed.png", added=None, deleted=None)
    monkeypatch.setattr(
        git_gd_qt, "run_image_score", lambda diff_args, entry: (12.34, 5.67)
    )
    window = git_gd_qt.DiffWindow(
        "repo", ["HEAD~"], [image], start_image_scores=False
    )

    assert window.model.data(window.model.index(0, 1)) == "rgb … a …"
    window.start_score_workers()
    assert window.score_pool.waitForDone(5000)
    app.processEvents()

    assert window.model.data(window.model.index(0, 1)) == "rgb 12.3 a 5.7"
    assert image.image_score_error is None
    window.close()


def test_image_score_failure_stays_out_of_binary_display(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_qt import DiffWindow

    app = QApplication.instance() or QApplication([])
    image = DiffEntry(path="broken.png", added=None, deleted=None)
    window = DiffWindow(
        "repo", [], [image], start_image_scores=False
    )

    window.remaining_image_scores = 1
    window.results_finished(image, None, None, "could not decode")

    index = window.model.index(0, 1)
    assert window.model.data(index) == "rgb … a …"
    assert window.model.data(index, 3) == "could not decode"
    window.close()
    assert app is not None


def test_text_statistics_fill_in_and_preserve_scroll_position(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_qt import DiffWindow

    app = QApplication.instance() or QApplication([])
    entries = [
        DiffEntry(path=f"file-{number:03}.txt", added=-1, deleted=-1)
        for number in range(100)
    ]
    window = DiffWindow(
        "repo", [], entries, start_image_scores=False
    )
    window.show()
    app.processEvents()
    window.table.selectRow(60)
    window.table.verticalScrollBar().setValue(30)
    selected_entry = window.model.entries[60]

    for number, entry in enumerate(entries):
        window.results_finished(
            (entry, number, number // 2, None),
            None,
            None,
            "text update",
        )
    window.results_finished(None, None, None, "text complete")
    app.processEvents()

    assert window.model.entries[
        window.table.currentIndex().row()
    ] is selected_entry
    assert window.table.verticalScrollBar().value() == 30
    assert "…" not in [
        window.model.data(window.model.index(row, 1))
        for row in range(window.model.rowCount())
    ]
    window.close()
    assert app is not None
