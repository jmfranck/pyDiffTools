import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from pydifftools.continuous import run_pandoc
from pydifftools.command_line import mfs


def _make_cli_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    (stub_dir / "argcomplete.py").write_text(
        "def autocomplete(parser):\n    return None\n"
    )
    (stub_dir / "numpy.py").write_text(
        "def array(*args, **kwargs):\n    return []\n"
        "def cumsum(*args, **kwargs):\n    return []\n"
        "def argmin(*args, **kwargs):\n    return 0\n"
    )
    (stub_dir / "psutil.py").write_text("pass\n")
    bib_path = Path("~/testlib.bib").expanduser()
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

    # 2. Provide minimal valid BibTeX content
    (tmp_path / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )

    # 3. Provide a VALID minimal CSL file.
    # An empty <style> tag causes 'CiteprocParseError: No citation
    # element present'.
    csl_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n<style'
        ' xmlns="http://purl.org/net/xbiblio/csl" version="1.0"'
        ' class="in-text">\n  <info>\n    <title>Minimal</title>\n   '
        " <id>minimal</id>\n    <updated>2023-01-01T00:00:00Z</updated>\n "
        " </info>\n  <citation>\n    <layout>\n      <text"
        ' variable="title"/>\n    </layout>\n  </citation>\n  <bibliography>\n'
        '    <layout>\n      <text variable="title"/>\n    </layout>\n '
        " </bibliography>\n</style>"
    )
    (tmp_path / "style.csl").write_text(csl_content)
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
