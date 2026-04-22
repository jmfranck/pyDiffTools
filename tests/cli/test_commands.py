import io
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pydifftools import continuous
from pydifftools.continuous import run_pandoc
from pydifftools.command_line import mfs
from pydifftools.command_registry import _COMMAND_SPECS
from pydifftools.git_gd import (
    DiffEntry,
    INSTALL_ALIAS_VALUE,
    build_difftool_command,
    build_entries,
)


def _make_cli_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env["HOME"] = str(home_dir)
    (stub_dir / "argcomplete.py").write_text(
        "def autocomplete(parser):\n    return None\n"
    )
    (stub_dir / "numpy.py").write_text(
        "def array(*args, **kwargs):\n    return []\n"
        "def cumsum(*args, **kwargs):\n    return []\n"
        "def argmin(*args, **kwargs):\n    return 0\n"
    )
    (stub_dir / "psutil.py").write_text("pass\n")
    bib_path = home_dir / "testlib.bib"
    bib_path.write_text("@book{dummy, title={Dummy}}\n")
    # Ensure CLI subprocesses can see conda-installed tools and libraries.
    env["PATH"] = f"/root/conda/bin:{env['PATH']}"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = (
            f"{stub_dir}:{repo_root}:/root/conda/lib/python3.12/site-packages:"
            f"{env['PYTHONPATH']}"
        )
    else:
        env["PYTHONPATH"] = (
            f"{stub_dir}:{repo_root}:/root/conda/lib/python3.12/site-packages"
        )
    env["PYDIFFTOOLS_FAKE_MATHJAX"] = "1"
    env["PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE"] = time.strftime(
        "%Y-%m-%d", time.gmtime()
    )
    return env


def write_minimal_bibliography_and_csl(target_dir):
    # Create citation support files that run_pandoc requires.
    (target_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (target_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<style'
        ' xmlns="http://purl.org/net/xbiblio/csl" version="1.0"'
        ' class="in-text">\n  <info>\n    <title>Minimal</title>\n   '
        " <id>minimal</id>\n    <updated>2023-01-01T00:00:00Z</updated>\n "
        " </info>\n  <citation>\n    <layout>\n      <text"
        ' variable="title"/>\n    </layout>\n  </citation>\n  <bibliography>\n'
        '    <layout>\n      <text variable="title"/>\n    </layout>\n '
        " </bibliography>\n</style>"
    )


def test_wgrph_missing_file(tmp_path):
    env = _make_cli_env(tmp_path)
    cmd = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "wgrph",
        str(tmp_path / "missing.yaml"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode != 0
    assert "YAML file not found" in proc.stderr


def test_file_completers_are_extension_specific(monkeypatch):
    from pydifftools import command_line

    class FakeFilesCompleter:
        def __init__(self, allowednames):
            self.allowednames = allowednames

    monkeypatch.setattr(command_line, "FilesCompleter", FakeFilesCompleter)

    parser = command_line.build_parser()
    wgrph_action = next(
        action
        for action in parser._pydifft_subparsers["wgrph"]._actions
        if action.dest == "yaml"
    )
    cpb_action = next(
        action
        for action in parser._pydifft_subparsers["cpb"]._actions
        if action.dest == "filename"
    )

    assert wgrph_action.completer.allowednames == ["*.yaml", "*.yml"]
    assert cpb_action.completer.allowednames == ["*.md"]


def _collect_argcomplete_suggestions(monkeypatch, comp_line):
    argcomplete = pytest.importorskip("argcomplete")
    from argcomplete import io as argcomplete_io
    from pydifftools import command_line

    parser = command_line.build_parser()
    output = io.StringIO()
    monkeypatch.setattr(
        argcomplete.CompletionFinder, "_init_debug_stream", lambda self: None
    )
    monkeypatch.setattr(argcomplete_io, "debug_stream", io.StringIO())
    monkeypatch.setenv("_ARGCOMPLETE", "1")
    monkeypatch.setenv("_ARGCOMPLETE_IFS", "\013")
    monkeypatch.setenv("COMP_LINE", comp_line)
    monkeypatch.setenv("COMP_POINT", str(len(comp_line)))

    class CompletionExit(Exception):
        def __init__(self, code):
            self.code = code

    def exit_method(code=0):
        raise CompletionExit(code)

    with pytest.raises(CompletionExit) as excinfo:
        try:
            argcomplete.autocomplete(
                parser,
                always_complete_options=False,
                exit_method=exit_method,
                output_stream=output,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            argcomplete.autocomplete(parser)
    assert excinfo.value.code == 0
    suggestions = [j.rstrip() for j in output.getvalue().split("\013") if j]
    assert argcomplete is not None
    return suggestions


def test_argcomplete_root_only_lists_subcommands(monkeypatch):
    suggestions = _collect_argcomplete_suggestions(monkeypatch, "pydifft ")

    assert sorted(suggestions) == sorted(_COMMAND_SPECS)
    assert all(not j.startswith("-") for j in suggestions)


def test_argcomplete_completes_subcommand_prefix(monkeypatch):
    suggestions = _collect_argcomplete_suggestions(monkeypatch, "pydifft wg")

    assert suggestions == ["wgrph"]


def test_argcomplete_wgrph_filters_to_yaml_files(monkeypatch, tmp_path):
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "phase1.txt").write_text("nope\n")
    (plans_dir / "phase2.yaml").write_text("nodes: {}\n")
    (plans_dir / "phase3.yml").write_text("nodes: {}\n")
    (plans_dir / "phone.md").write_text("# nope\n")
    monkeypatch.chdir(tmp_path)

    suggestions = _collect_argcomplete_suggestions(
        monkeypatch, "pydifft wgrph -d plans/ph"
    )

    assert suggestions == ["plans/phase2.yaml", "plans/phase3.yml"]


def test_tex2qmd_cli(tmp_path):
    env = _make_cli_env(tmp_path)
    sample = (
        Path(__file__).resolve().parents[1] / "fixtures" / "tex" / "sample.tex"
    )
    target = tmp_path / "example.tex"
    target.write_text(sample.read_text())
    cmd = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "tex2qmd",
        str(target),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=tmp_path
    )
    # --- NEW DEBUGGING LINES ---
    if proc.returncode != 0:
        print("--- Subprocess STDOUT ---")
        print(proc.stdout)
        print("--- Subprocess STDERR ---")
        print(proc.stderr)
        print("-------------------------")
    # ---------------------------
    assert proc.returncode == 0
    assert target.with_suffix(".qmd").exists()


def test_qmdinit_and_qmdb(tmp_path):
    env = _make_cli_env(tmp_path)
    project_dir = tmp_path / "proj"
    cmd_init = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "qmdinit",
        str(project_dir),
    ]
    proc_init = subprocess.run(
        cmd_init, capture_output=True, text=True, env=env
    )
    assert proc_init.returncode == 0
    mathjax = (
        project_dir / "_template" / "mathjax" / "es5" / "tex-mml-chtml.js"
    )
    assert mathjax.exists()
    cmd_build = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "qmdb",
        "--no-browser",
    ]
    proc_build = subprocess.run(
        cmd_build,
        capture_output=True,
        text=True,
        env=env,
        cwd=project_dir,
    )
    assert proc_build.returncode == 0
    built = project_dir / "_build" / "project1" / "subproject1" / "tasks.html"
    assert built.exists()


def test_markdown_outline_reorder(tmp_path):
    env = _make_cli_env(tmp_path)
    sample = (
        Path(__file__).resolve().parents[1] / "fixtures" / "md" / "sample.md"
    )
    target = tmp_path / "sample.md"
    target.write_text(sample.read_text())
    cmd_extract = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "xomd",
        str(target),
    ]
    proc_extract = subprocess.run(
        cmd_extract, capture_output=True, text=True, env=env
    )
    assert proc_extract.returncode == 0
    outline_path = tmp_path / "sample_outline.md"
    assert outline_path.exists()
    outline_path.write_text(
        "*\tProject Notes\n"
        "\t*\tSecond Topic\n"
        "\t*\tDeep Dive\n"
        "\t\t\t\t*\tHidden Notes\n"
        "\t*\tFirst Topic\n"
    )
    cmd_reorder = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "xomdreorder",
        str(target),
    ]
    proc_reorder = subprocess.run(
        cmd_reorder, capture_output=True, text=True, env=env
    )
    assert proc_reorder.returncode == 0
    content = target.read_text()
    assert content.index("## Second Topic") < content.index("## First Topic")
    assert "##### Hidden Notes" in content


def test_gd_install_sets_git_alias(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(
            {
                "cmd": cmd,
                "check": check,
                "capture_output": capture_output,
                "text": text,
            }
        )
        if cmd[:5] == [
            "git",
            "config",
            "--global",
            "--get",
            "difftool.mygvim.cmd",
        ]:
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr=""
            )
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("pydifftools.git_gd.subprocess.run", fake_run)

    from pydifftools import command_line

    command_line.main(["gd", "--install"])
    assert calls[0]["cmd"] == [
        "git",
        "config",
        "--global",
        "alias.gd",
        INSTALL_ALIAS_VALUE,
    ]
    assert calls[0]["check"] is True
    out = capsys.readouterr().out
    assert "alias.gd" in out
    assert "difftool.mygvim.cmd" in out


def test_gd_install_rejects_diff_args():
    from pydifftools import command_line

    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["gd", "--install", "HEAD~1"])
    assert "does not take diff args" in str(excinfo.value)


def test_gd_build_entries_sorts_by_change_count(monkeypatch):
    monkeypatch.setattr(
        "pydifftools.git_gd.changed_entries",
        lambda diff_args, pathspec: [
            DiffEntry(path="alpha.txt", added=0, deleted=0),
            DiffEntry(path="binary.bin", added=0, deleted=0),
            DiffEntry(path="beta.txt", added=0, deleted=0),
        ],
    )

    def fake_numstat(diff_args, paths):
        values = {
            "alpha.txt": (3, 4),
            "binary.bin": (None, None),
            "beta.txt": (10, 1),
        }
        return values[paths[0]]

    monkeypatch.setattr("pydifftools.git_gd.numstat_for_paths", fake_numstat)

    diff_args, entries = build_entries(["HEAD~1", "--", "docs"])
    assert diff_args == ["HEAD~1"]
    assert [entry.path for entry in entries] == [
        "beta.txt",
        "alpha.txt",
        "binary.bin",
    ]


def test_gd_build_entries_tracks_renamed_file(tmp_path):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True
        )
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)
        Path("old.txt").write_text("one\ntwo\nthree\n")
        subprocess.run(["git", "add", "old.txt"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], check=True)
        subprocess.run(["git", "mv", "old.txt", "new.txt"], check=True)
        Path("new.txt").write_text("one\nTWO\nthree\n")

        diff_args, entries = build_entries(["HEAD"])
    finally:
        os.chdir(cwd)

    assert diff_args == ["HEAD"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.status.startswith("R")
    assert entry.old_path == "old.txt"
    assert entry.new_path == "new.txt"
    assert entry.path == "new.txt"
    assert entry.added == 1
    assert entry.deleted == 1
    assert entry.diff_paths == ["old.txt", "new.txt"]
    assert entry.display_path == "old.txt\n  → new.txt"


def test_gd_pathspec_keeps_renamed_file_status(tmp_path):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True
        )
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)
        Path("old.txt").write_text("one\ntwo\nthree\n")
        subprocess.run(["git", "add", "old.txt"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], check=True)
        subprocess.run(["git", "mv", "old.txt", "new.txt"], check=True)
        Path("new.txt").write_text("one\nTWO\nthree\n")

        _diff_args, entries_from_new_path = build_entries(
            ["HEAD", "--", "new.txt"]
        )
        _diff_args, entries_from_old_path = build_entries(
            ["HEAD", "--", "old.txt"]
        )
    finally:
        os.chdir(cwd)

    for entries in (entries_from_new_path, entries_from_old_path):
        assert len(entries) == 1
        entry = entries[0]
        assert entry.status.startswith("R")
        assert entry.old_path == "old.txt"
        assert entry.new_path == "new.txt"
        assert entry.diff_paths == ["old.txt", "new.txt"]


def test_gd_diff_entry_marks_exact_renames():
    entry = DiffEntry(
        path="new.txt",
        added=0,
        deleted=0,
        status="R100",
        old_path="old.txt",
        new_path="new.txt",
    )

    assert entry.is_exact_rename
    assert entry.diff_paths == ["old.txt", "new.txt"]
    assert entry.display_path == "old.txt → new.txt"


def test_gd_difftool_command_wraps_renames_for_merged_side():
    entry = DiffEntry(
        path="new.txt",
        added=1,
        deleted=1,
        status="R071",
        old_path="old.txt",
        new_path="new.txt",
    )

    cmd = build_difftool_command(
        ["HEAD"],
        entry,
        tool_cmd='~/gvim.sh -f -d -- "$LOCAL" "$MERGED"',
    )

    assert cmd[:3] == [
        "git",
        "-c",
        (
            'difftool.pydifft-gd-rename.cmd=MERGED="$REMOTE"; '
            '~/gvim.sh -f -d -- "$LOCAL" "$MERGED"'
        ),
    ]
    assert cmd[3:] == [
        "difftool",
        "--tool=pydifft-gd-rename",
        "--no-prompt",
        "--find-renames",
        "HEAD",
        "--",
        "old.txt",
        "new.txt",
    ]


def test_cpb_hides_low_headers(tmp_path):
    env = _make_cli_env(tmp_path)

    # 1. Provide Markdown with a citation to avoid 'No citation element'
    # errors
    markdown_content = (
        "# Visible\n\n"
        "This text includes a reference [@dummy_ref].\n\n"
        "##### Hidden Header\nBody text.\n"
    )
    markdown_file = tmp_path / "notes.md"
    markdown_file.write_text(markdown_content)

    write_minimal_bibliography_and_csl(tmp_path)
    html_file = tmp_path / "notes.html"
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch.dict(os.environ, env, clear=False):
            run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)
    html_content = html_file.read_text()
    assert "h5, h6 { display: none; }" in html_content
    assert "h4" not in html_content.split("display:")[-1]


def test_mfs_starts_cpb_when_socket_missing(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nneedle\nomega\n")
    (tmp_path / "other.md").write_text("does not match\n")

    calls = {
        "connect": 0,
        "sendall": [],
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            calls["connect"] += 1
            if calls["connect"] == 1:
                raise OSError("socket not ready")

        def sendall(self, payload):
            calls["sendall"].append(payload)

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            with patch("pydifftools.command_line.os.fork", return_value=123):
                with patch("pydifftools.command_line.time.sleep"):
                    mfs("needle")
        assert calls["connect"] >= 2
        assert calls["sendall"] == [b"needle"]
    finally:
        os.chdir(cwd)


def test_mfs_waits_up_to_20_seconds_for_socket(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nneedle\nomega\n")

    calls = {
        "connect": 0,
        "sleep": 0,
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            calls["connect"] += 1
            raise OSError("socket not ready")

        def sendall(self, _payload):
            return

        def close(self):
            return

    def fake_sleep(_seconds):
        calls["sleep"] += 1

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            with patch("pydifftools.command_line.os.fork", return_value=123):
                with patch("pydifftools.command_line.time.sleep", fake_sleep):
                    try:
                        mfs("needle")
                        assert False, "Expected mfs to raise RuntimeError"
                    except RuntimeError as exc:
                        assert "within 20 seconds" in str(exc)
        # We try cpb and qmdb sockets each time: one initial pass plus
        # 80 retry passes gives 162 connection attempts total.
        assert calls["connect"] == 162
        assert calls["sleep"] == 80
    finally:
        os.chdir(cwd)


def test_mfs_uses_qmdb_socket_when_cpb_socket_missing(tmp_path):
    calls = {
        "connect": [],
        "sendall": [],
        "fork": 0,
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, address):
            calls["connect"].append(address)
            # First (cpb) socket fails, second (qmdb) socket succeeds.
            if len(calls["connect"]) == 1:
                raise OSError("cpb socket missing")

        def sendall(self, payload):
            calls["sendall"].append(payload)

        def close(self):
            return

    def fake_fork():
        calls["fork"] += 1
        return 123

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            with patch("pydifftools.command_line.os.fork", fake_fork):
                mfs("needle")
        assert calls["fork"] == 0
        assert len(calls["connect"]) == 2
        assert calls["sendall"] == [b"needle"]
    finally:
        os.chdir(cwd)


def test_mfs_strips_markdown_markup_before_search(tmp_path):
    calls = {
        "sendall": [],
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            return

        def sendall(self, payload):
            calls["sendall"].append(payload)

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            mfs("**Result** near @fig:overview [@smith2024]")
        assert calls["sendall"] == [b"Result near"]
    finally:
        os.chdir(cwd)


def test_mfs_marker_regex_is_case_insensitive(tmp_path):
    calls = {
        "sendall": [],
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            return

        def sendall(self, payload):
            calls["sendall"].append(payload)

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            mfs("Result before @FIG:overview should truncate")
        assert calls["sendall"] == [b"Result before"]
    finally:
        os.chdir(cwd)


def test_run_pandoc_adds_css_lua_and_js_files_from_markdown_directory(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text(
        "---\n"
        "pydifft-lua-filters:\n"
        "  - cleanup.lua\n"
        "  - numbers.lua\n"
        "---\n"
        "# Title\n"
    )
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    (project_dir / "site.css").write_text("body { color: red; }\n")
    (project_dir / "print.css").write_text(
        "@media print { body { color: black; } }\n"
    )
    (project_dir / "cleanup.lua").write_text("return {}\n")
    (project_dir / "numbers.lua").write_text("return {}\n")
    (project_dir / "extras.js").write_text('console.log("extras");\n')
    (project_dir / "widgets.js").write_text('console.log("widgets");\n')
    html_file = tmp_path / "notes.html"
    captured_command = {}

    # Skip external tool checks and capture the exact pandoc command.
    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(command):
        captured_command["value"] = command
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write(
                '<html><head><script id="MathJax-script" '
                'src="MathJax-3.1.2/es5/tex-mml-chtml.js"></script></head>'
                "<body>ok</body></html>"
            )

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    css_pairs = []
    lua_pairs = []
    command = captured_command["value"]
    for index, token in enumerate(command[:-1]):
        if token == "--css":
            css_pairs.append(command[index + 1])
        if token == "--lua-filter":
            lua_pairs.append(command[index + 1])
    assert css_pairs == [
        str(project_dir / "print.css"),
        str(project_dir / "site.css"),
    ]
    assert lua_pairs == [
        str(project_dir / "cleanup.lua"),
        str(project_dir / "numbers.lua"),
    ]
    html_content = html_file.read_text()
    assert "MathJax-script" in html_content
    assert (
        '<script src="' + str(project_dir / "extras.js") + '"></script>'
    ) in html_content
    assert (
        '<script src="' + str(project_dir / "widgets.js") + '"></script>'
    ) in html_content


def test_run_pandoc_skips_unlisted_lua_filters_by_default(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    (project_dir / "author-info-blocks.lua").write_text("return {}\n")
    html_file = tmp_path / "notes.html"
    captured_command = {}

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(command):
        captured_command["value"] = command
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    assert "--lua-filter" not in captured_command["value"]


def test_run_pandoc_raises_when_pandoc_does_not_create_html(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    html_file = tmp_path / "notes.html"

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )
    monkeypatch.setattr(
        "pydifftools.continuous.subprocess.run",
        lambda _command: subprocess.CompletedProcess(_command, 0),
    )

    with pytest.raises(RuntimeError, match="did not create"):
        run_pandoc(str(markdown_file), str(html_file))


def test_run_pandoc_raises_when_pandoc_fails(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    html_file = tmp_path / "notes.html"

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )
    monkeypatch.setattr(
        "pydifftools.continuous.subprocess.run",
        lambda _command: subprocess.CompletedProcess(_command, 1),
    )

    with pytest.raises(RuntimeError, match="Pandoc failed"):
        run_pandoc(str(markdown_file), str(html_file))


def test_run_pandoc_copies_comment_assets_when_comment_tags_present(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n\n<comment>hello</comment>\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    html_file = tmp_path / "notes.html"

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(_command):
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    assert (project_dir / "comments.css").exists()
    assert (project_dir / "comment_tags.lua").exists()
    assert (project_dir / "comment_toggle.js").exists()


def test_run_pandoc_does_not_overwrite_existing_comment_assets(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n\n<comment>hello</comment>\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    for asset_name in [
        "comments.css",
        "comment_tags.lua",
        "comment_toggle.js",
    ]:
        (project_dir / asset_name).write_text(f"local override {asset_name}\n")
    html_file = tmp_path / "notes.html"

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(_command):
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    for asset_name in [
        "comments.css",
        "comment_tags.lua",
        "comment_toggle.js",
    ]:
        assert (project_dir / asset_name).read_text() == (
            f"local override {asset_name}\n"
        )


def test_append_autorefresh_persists_comment_hidden_state(tmp_path):
    html_file = tmp_path / "notes.html"
    html_file.write_text("<html><head></head><body>ok</body></html>")

    fake_handler = type("FakeHandler", (), {"html_file": str(html_file)})()
    continuous.Handler.append_autorefresh(fake_handler)

    html_content = html_file.read_text()
    assert "commentHiddenBubbleIndexes" in html_content
    assert "commentBubbleSelector" in html_content
    assert "classList.contains('comment-hidden')" in html_content
    assert "classList.add('comment-hidden')" in html_content


def test_comment_filter_mode_switches_to_margin_and_back(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    active_filter = project_dir / "comment_tags.lua"
    inactive_filter = project_dir / "comment_tags.lua.inactive"
    active_filter.write_text("normal filter\n")

    continuous._set_comment_filter_mode(str(project_dir), True)
    active_margin = active_filter.read_text()
    assert continuous.MARGIN_COMMENTS_FILTER_MARKER in active_margin
    assert inactive_filter.read_text() == "normal filter\n"

    continuous._set_comment_filter_mode(str(project_dir), False)
    assert active_filter.read_text() == "normal filter\n"
    assert (
        continuous.MARGIN_COMMENTS_FILTER_MARKER in inactive_filter.read_text()
    )


def test_comment_filter_mode_restores_repo_default_when_inactive_missing(
    tmp_path,
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    active_filter = project_dir / "comment_tags.lua"
    inactive_filter = project_dir / "comment_tags.lua.inactive"

    margin_repo_filter = (
        Path(continuous.__file__).resolve().parent / "comment_tags_margin.lua"
    )
    active_filter.write_text(margin_repo_filter.read_text())

    continuous._set_comment_filter_mode(str(project_dir), False)

    assert active_filter.exists()
    assert inactive_filter.exists()
    assert (
        continuous.MARGIN_COMMENTS_FILTER_MARKER
        not in active_filter.read_text()
    )
    assert (
        continuous.MARGIN_COMMENTS_FILTER_MARKER in inactive_filter.read_text()
    )


def test_margin_comment_filter_uses_overlay_style_for_inline_comments():
    margin_filter = (
        Path(continuous.__file__).resolve().parent / "comment_tags_margin.lua"
    ).read_text()
    assert "comment-inline-margin" in margin_filter
    assert "comment-margin-left" in margin_filter
    assert "comment-inline-break-before" in margin_filter
    assert "comment-inline-break-after" in margin_filter
    assert "comment-pin comment-pin-block" in margin_filter
    assert "pandoc.RawInline(" in margin_filter


def test_run_pandoc_comment_tag_regression_end_to_end(tmp_path):
    # This markdown reproduces the current failing mode where list content
    # inside <comment> leaks into the main body text.
    markdown_content = """Because these contributions have a smaller
linewidth and because the amplitude of the
derivative signal is inversely proportional
to the square of the linewidth,
the spectrum responds correspondingly dramatically
to contributions from the RMs with low local
concentration.
<comment>
☐ TODO:
    Include a comparison of actual lines in the
    plot.
</comment>
<comment>
☐ TODO:
    Make sure the git repo has the updated
    version of the plot that you crafted and
    presented on slack!!
</comment>
Correspondingly,
<comment>
☐ TODO:
Here, you want to guide people more
explicitly through exactly what you are
talking about:

* For people unaccustomed to ESR spectra, you
    want to specifically talk in terms of the
    "initial positive maximum" and the "final
    minimum".
* You need to be sure that you're
    explaining that in this concentration
    range, you transition from three resolved
    hyperfine lines to a single, broad line.
</comment>
ESR measurements at lower water loading include [@dummy_ref].

<comment>
☐ TODO:
    I think a lot of the following caption is
    description.
</comment>

::: {.comment-right}
☐ TODO:
It's still unclear what causes the low-$E_a$ region.
:::
"""
    markdown_file = tmp_path / "notes.md"
    html_file = tmp_path / "notes.html"
    markdown_file.write_text(markdown_content)
    write_minimal_bibliography_and_csl(tmp_path)

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)

    html_content = html_file.read_text()

    # Ensure comments generated from <comment> tags and .comment-right blocks
    # are rendered as bubbles in the output html.
    assert html_content.count('class="comment-pin"') >= 3
    assert 'class="comment-right"' in html_content

    # Regression assertion: this phrase should be present inside a comment
    # overlay and not leaked into a main-body list.
    phrase = "For people unaccustomed to ESR spectra"
    assert phrase in html_content
    assert '<div class="comment-overlay comment-right"' in html_content
    assert "<ul>" in html_content

    # Confirm the bullet list is inside a comment overlay block.
    overlay_with_list = False
    sections = html_content.split('<div class="comment-overlay comment-right"')
    for section in sections[1:]:
        if phrase in section and "<ul>" in section:
            overlay_with_list = True
            break
    assert overlay_with_list


def test_comment_css_arrow_geometry_constants(tmp_path):
    # Keep explicit geometry values in test constants so future style edits can
    # update one place and immediately see behavior changes in this test.
    arrow_height_px = 8
    arrow_width_px = 8
    left_arrow_width_px = 16
    bubble_separation_rem = 0.5
    overlap_shift_rem = 1
    overlay_right_shift_rem = 0.45
    overlay_rise_rem = 0.65
    inline_rise_rem = 0.35

    markdown_file = tmp_path / "notes.md"
    html_file = tmp_path / "notes.html"
    markdown_file.write_text(
        "Body [@dummy_ref].\n\n<comment>Inline bubble</comment>\n"
    )
    write_minimal_bibliography_and_csl(tmp_path)

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)

    css_content = (tmp_path / "comments.css").read_text()
    js_content = (tmp_path / "comment_toggle.js").read_text()

    # Left/right pointer triangles should use the configured arrow size.
    assert "span.comment-pin > span.comment-right::before" in css_content
    assert "span.comment-pin > span.comment-left::before" in css_content
    assert ".comment-overlay.comment-right::before" in css_content
    assert ".comment-overlay.comment-left::before" in css_content
    assert ".comment-overlay.comment-margin-left" in css_content
    assert ".comment-inline-break-marker" in css_content
    assert "var(--comment-left-arrow-width)" in css_content
    assert "var(--comment-arrow-width)" in css_content
    assert "var(--comment-arrow-height)" in css_content

    # The configured css variables control arrow height/width and overlap
    # shift.
    assert f"--comment-arrow-height: {arrow_height_px}px;" in css_content
    assert f"--comment-arrow-width: {arrow_width_px}px;" in css_content
    assert (
        f"--comment-left-arrow-width: {left_arrow_width_px}px;" in css_content
    )
    assert f"--comment-overlap-shift: {overlap_shift_rem}rem;" in css_content
    assert (
        f"--comment-overlay-right-shift: {overlay_right_shift_rem}rem;"
        in css_content
    )
    assert f"--comment-overlay-rise: {overlay_rise_rem}rem;" in css_content
    assert f"--comment-inline-rise: {inline_rise_rem}rem;" in css_content

    # Bubble separation (gap) must match the configured value for both sides.
    assert f"left: {bubble_separation_rem}rem;" in css_content
    assert f"right: {bubble_separation_rem}rem;" in css_content
    assert f"--comment-gap: {bubble_separation_rem}rem;" in css_content

    # JS should convert css length variables to pixels before geometry math,
    # otherwise rem-based values do not affect rendered spacing correctly.
    assert "--comment-overlap-shift" in js_content
    assert "--comment-overlay-right-shift" in js_content
    assert "--comment-overlay-rise" in js_content
    assert "--comment-inline-rise" in js_content
    assert "--comment-gap" in js_content
    assert "function cssLengthToPx" in js_content
    assert "function cssVariableLengthPx" in js_content
    assert "SELECTOR_INLINE" in js_content
    assert "useMobileFlow" in js_content
    assert "comment-margin-left" in js_content
    assert "bubble.style.transform" in js_content
    assert "left = ax + gap + overlayRightShift" in js_content
    assert "const top = ay - overlayRise" in js_content


def test_mfs_errors_when_no_matching_markdown(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nbeta\n")

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            raise OSError("socket not ready")

        def sendall(self, _payload):
            return

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            try:
                mfs("needle")
                assert False, "Expected mfs to raise RuntimeError"
            except RuntimeError as exc:
                assert "could not find the requested text" in str(exc)
    finally:
        os.chdir(cwd)
