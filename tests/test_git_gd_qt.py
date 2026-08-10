from pydifftools.git_gd import DiffEntry


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
    window._image_score_finished(first, 12.34, 4.56, None)
    window._image_score_finished(second, 45.67, 8.91, None)

    assert window.model.entries == [text, second, first]
    assert window.model.data(window.model.index(1, 1)) == "rgb 45.7 a 8.9"
    assert window.model.data(window.model.index(2, 1)) == "rgb 12.3 a 4.6"
    assert window.model.entries[window.table.currentIndex().row()] is second
    window.close()
    assert app is not None


def test_image_score_failure_stays_out_of_binary_display(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_qt import DiffWindow

    app = QApplication.instance() or QApplication([])
    image = DiffEntry(path="broken.png", added=None, deleted=None)
    window = DiffWindow(
        "repo", [], [image], start_image_scores=False
    )

    window._image_score_finished(image, None, None, "could not decode")

    index = window.model.index(0, 1)
    assert window.model.data(index) == "rgb ? a ?"
    assert window.model.data(index, 3) == "could not decode"
    window.close()
    assert app is not None
