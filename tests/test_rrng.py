import itertools
import sys
import textwrap
from pathlib import Path
from types import ModuleType

# Make sure the repository root is importable so the CLI module can be exercised in place.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Provide a minimal numpy stub so importing the CLI does not require the real dependency.
numpy_stub = ModuleType("numpy")
numpy_stub.array = lambda data: list(data)
numpy_stub.cumsum = lambda data: list(itertools.accumulate(data))
numpy_stub.argmin = (
    lambda data: min(range(len(data)), key=lambda i: abs(data[i])) if data else 0
)
sys.modules.setdefault("numpy", numpy_stub)

# Stub out heavyweight optional dependencies referenced by unrelated commands.
selenium_stub = ModuleType("selenium")
selenium_stub.webdriver = ModuleType("selenium.webdriver")
sys.modules.setdefault("selenium", selenium_stub)
sys.modules.setdefault("selenium.webdriver", selenium_stub.webdriver)
sys.modules.setdefault("psutil", ModuleType("psutil"))
watchdog_stub = ModuleType("watchdog")
watchdog_observers_stub = ModuleType("watchdog.observers")
watchdog_observers_stub.Observer = object
watchdog_events_stub = ModuleType("watchdog.events")
watchdog_events_stub.FileSystemEventHandler = object
sys.modules.setdefault("watchdog", watchdog_stub)
sys.modules.setdefault("watchdog.observers", watchdog_observers_stub)
sys.modules.setdefault("watchdog.events", watchdog_events_stub)
nbformat_stub = ModuleType("nbformat")
nbformat_stub.NO_CONVERT = object()
nbformat_stub.read = lambda *args, **kwargs: None
sys.modules.setdefault("nbformat", nbformat_stub)
argcomplete_stub = ModuleType("argcomplete")
argcomplete_stub.autocomplete = lambda parser: None
sys.modules.setdefault("argcomplete", argcomplete_stub)
separate_stub = ModuleType("pydifftools.separate_comments")
separate_stub.tex_sepcomments = lambda *args, **kwargs: None
sys.modules.setdefault("pydifftools.separate_comments", separate_stub)
unseparate_stub = ModuleType("pydifftools.unseparate_comments")
unseparate_stub.tex_unsepcomments = lambda *args, **kwargs: None
sys.modules.setdefault("pydifftools.unseparate_comments", unseparate_stub)

import pytest

from pydifftools import command_line


def test_rrng_rearranges_tex(tmp_path):
    # Create a TeX file and rearrangement plan that exercises comments, substitutions, and scratch output.
    tex_path = tmp_path / "sample.tex"
    tex_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    plan_path = tmp_path / "sample.rrng"
    plan_path.write_text(
        textwrap.dedent(
            """\
            # Rearrangement Plan
            1 scratch
            2 s/a/A/
            3 s/m/Z/g
            """
        ),
        encoding="utf-8",
    )

    # Invoke the rrng subcommand through the CLI entry point to exercise the registered handler.
    command_line.main(["rrng", str(tex_path), str(plan_path)])

    # Verify that the TeX file now contains the rearranged lines with the scratch section appended.
    assert (
        tex_path.read_text(encoding="utf-8")
        == "% Rearrangement Plan\nbetA\ngaZZa\n% --- SCRATCH ---\n% alpha\n"
    )


def test_rrng_requires_all_lines(tmp_path):
    # Confirm that missing source lines cause the command to abort with a helpful error message.
    tex_path = tmp_path / "missing.tex"
    tex_path.write_text("one\ntwo\n", encoding="utf-8")
    plan_path = tmp_path / "missing.rrng"
    plan_path.write_text(
        textwrap.dedent(
            """
            1
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["rrng", str(tex_path), str(plan_path)])

    assert "ERROR: Plan missing lines: [2]" in str(excinfo.value)


def test_rrng_rejects_duplicate_lines(tmp_path):
    # Confirm that duplicate line references surface a clear error so the user fixes the plan file.
    tex_path = tmp_path / "dupe.tex"
    tex_path.write_text("red\nblue\n", encoding="utf-8")
    plan_path = tmp_path / "dupe.rrng"
    plan_path.write_text(
        textwrap.dedent(
            """
            1
            1
            2
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["rrng", str(tex_path), str(plan_path)])

    assert "ERROR: Plan duplicated lines: [1]" in str(excinfo.value)
