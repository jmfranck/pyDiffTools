import importlib.util
import os
import subprocess
import sys
import time
import types
from pathlib import Path

# Provide a numpy stub so importing the CLI module does not pull heavy deps in tests.
if "numpy" not in sys.modules and importlib.util.find_spec("numpy") is None:
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.array = lambda *args, **kwargs: []
    numpy_stub.cumsum = lambda *args, **kwargs: []
    numpy_stub.argmin = lambda *args, **kwargs: 0
    sys.modules["numpy"] = numpy_stub

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

from pydifftools import command_line


def _make_cli_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
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
    bib_path = Path("/home/jmfranck/My Library.bib")
    bib_path.parent.mkdir(parents=True, exist_ok=True)
    bib_path.write_text("@book{dummy, title={Dummy}}\n")
    pandoc_script = bin_dir / "pandoc"
    pandoc_script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, pathlib\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('-o') + 1] if '-o' in args else 'out.html'\n"
        "src = args[0] if args else ''\n"
        "data = pathlib.Path(src).read_text() if src else ''\n"
        "path = pathlib.Path(out)\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(data or '<html><body>stub</body></html>')\n"
    )
    pandoc_script.chmod(0o755)
    crossref_script = bin_dir / "pandoc-crossref"
    crossref_script.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stdout.write(sys.stdin.read())\n"
    )
    crossref_script.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PYTHONPATH"] = f"{stub_dir}:{repo_root}"
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
