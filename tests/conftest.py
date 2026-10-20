import os
import sys
from pathlib import Path

import pytest

# Ensure Jupyter uses the platformdirs path to avoid deprecation warnings.
os.environ.setdefault("JUPYTER_PLATFORM_DIRS", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_notice: let pydifftools.zotero.show_notice launch its window",
    )


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Keep Qt alive until all test windows have been destroyed."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application
    # Shut down while Python and its Qt wrappers are still intact, rather
    # than leaving Qt's destruction order to interpreter finalization.
    application.shutdown()


@pytest.fixture(autouse=True)
def qt_windows(qt_application):
    """Delete closed windows too, including ones retained by signal cycles."""
    from PySide6.QtCore import QCoreApplication, QEvent

    yield
    # Deliver queued signals and zero-delay callbacks while their windows
    # still exist (the diff viewer defers scroll restoration this way).
    qt_application.processEvents()
    for window in qt_application.topLevelWidgets():
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def notices(request, monkeypatch):
    """Record cpb notices instead of opening windows on the desktop."""
    shown = []
    if request.node.get_closest_marker("real_notice") is None:
        from pydifftools import zotero

        monkeypatch.setattr(
            zotero,
            "show_notice",
            lambda message, once=False: shown.append(message),
        )
    return shown
