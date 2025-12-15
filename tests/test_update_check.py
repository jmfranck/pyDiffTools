import importlib.util
import json
import io
import os
import sys
import time
import types
import urllib.error

# Provide a tiny numpy stub so importing the CLI module does not require heavy deps
# when running the tests in isolation.
if "numpy" not in sys.modules and importlib.util.find_spec("numpy") is None:
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.array = lambda *args, **kwargs: []
    numpy_stub.cumsum = lambda *args, **kwargs: []
    numpy_stub.argmin = lambda *args, **kwargs: 0
    sys.modules["numpy"] = numpy_stub

# Avoid side effects from modules that alter stdout during import when loading the
# CLI for these tests.
if "pydifftools.separate_comments" not in sys.modules:
    separate_stub = types.ModuleType("pydifftools.separate_comments")

    def tex_sepcomments(*args, **kwargs):
        return None

    separate_stub.tex_sepcomments = tex_sepcomments
    sys.modules["pydifftools.separate_comments"] = separate_stub

if "pydifftools.unseparate_comments" not in sys.modules:
    unseparate_stub = types.ModuleType("pydifftools.unseparate_comments")

    def tex_unsepcomments(*args, **kwargs):
        return None

    unseparate_stub.tex_unsepcomments = tex_unsepcomments
    sys.modules["pydifftools.unseparate_comments"] = unseparate_stub

if "pydifftools.continuous" not in sys.modules:
    continuous_stub = types.ModuleType("pydifftools.continuous")

    def watch(*args, **kwargs):
        return None

    continuous_stub.watch = watch
    sys.modules["pydifftools.continuous"] = continuous_stub

if "argcomplete" not in sys.modules:
    argcomplete_stub = types.ModuleType("argcomplete")

    def autocomplete(parser):
        return None

    argcomplete_stub.autocomplete = autocomplete
    sys.modules["argcomplete"] = argcomplete_stub

from pydifftools import update_check
from pydifftools import command_line


def test_check_update_reports_newer_release(monkeypatch):
    # Simulate installed version and a newer one on PyPI.
    monkeypatch.setattr(update_check.importlib.metadata, "version", lambda name: "1.0.0")

    payload = json.dumps({"info": {"version": "2.0.0"}}).encode("utf-8")

    class DummyResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout=1):
        return DummyResponse(payload)

    monkeypatch.setattr(update_check.urllib.request, "urlopen", fake_urlopen)

    current_version, latest_version, is_outdated = update_check.check_update("pyDiffTools")
    assert current_version == "1.0.0"
    assert latest_version == "2.0.0"
    assert is_outdated is True


def test_check_update_handles_offline(monkeypatch):
    # Offline or timeout errors should not raise and should not report an update.
    monkeypatch.setattr(update_check.importlib.metadata, "version", lambda name: "1.0.0")

    def offline_urlopen(url, timeout=1):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(update_check.urllib.request, "urlopen", offline_urlopen)

    current_version, latest_version, is_outdated = update_check.check_update("pyDiffTools")
    assert current_version == "1.0.0"
    assert latest_version is None
    assert is_outdated is False


def test_cli_update_check_runs_once_per_day(monkeypatch):
    # The CLI should only call out to PyPI once per UTC day and should set
    # the env var so subsequent invocations can skip the check.
    monkeypatch.delenv("PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE", raising=False)

    calls = []

    def fake_check(package_name, timeout=1):
        calls.append((package_name, timeout))
        return "1.0.0", "1.0.1", True

    monkeypatch.setattr(command_line.update_check, "check_update", fake_check)
    monkeypatch.setattr(command_line.sys, "stderr", io.StringIO())

    command_line.main([])

    today = time.strftime("%Y-%m-%d", time.gmtime())
    assert "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE" in os.environ
    assert os.environ["PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE"] == today
    assert len(calls) == 1

    command_line.main([])
    assert len(calls) == 1
