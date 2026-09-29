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
