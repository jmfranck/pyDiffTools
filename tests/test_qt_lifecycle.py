from pathlib import Path
import subprocess
import sys


def test_qt_windows_are_deleted_before_application_shutdown(tmp_path):
    conftest = Path(__file__).with_name("conftest.py").read_text()
    (tmp_path / "conftest.py").write_text(
        conftest
        + """

def pytest_sessionfinish(session, exitstatus):
    from PySide6.QtWidgets import QApplication
    assert QApplication.instance() is None
"""
    )
    (tmp_path / "test_windows.py").write_text(
        """
from PySide6.QtWidgets import QApplication, QPushButton
from shiboken6 import isValid

retained_windows = []
retained_applications = []


def test_closed_window():
    application = QApplication.instance() or QApplication([])
    retained_applications.append(application)
    window = QPushButton("Close")
    # Keep both a Python reference and a signal closure alive past the test.
    window.clicked.connect(lambda: window.close())
    window.close()
    retained_windows.append(window)
    assert isValid(application)


def test_previous_window_is_deleted():
    assert not isValid(retained_windows[0])
    assert QApplication.instance() is retained_applications[0]
    assert isValid(retained_applications[0])
"""
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "2 passed" in completed.stdout
