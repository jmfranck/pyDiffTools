import importlib.util
import json
import io
import os
import sys
import time
import types
import urllib.error


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
