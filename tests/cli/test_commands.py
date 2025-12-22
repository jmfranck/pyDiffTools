import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from pydifftools.continuous import run_pandoc


def _make_cli_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pandoc_script = bin_dir / "pandoc"
    pandoc_script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, pathlib\n"
        "args = sys.argv[1:]\n"
        "out_index = args.index('-o') + 1 if '-o' in args else None\n"
        "out = args[out_index] if out_index is not None else 'out.html'\n"
        "inputs = [j for j in args if not j.startswith('-') and j != out]\n"
        "src = inputs[-1] if inputs else ''\n"
        "data = pathlib.Path(src).read_text() if src else ''\n"
        "html = '<html><head><title>stub</title></head><body>' + data + '</body></html>'\n"
        "path = pathlib.Path(out)\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(html)\n"
    )
    pandoc_script.chmod(0o755)
    crossref_script = bin_dir / "pandoc-crossref"
    crossref_script.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stdout.write(sys.stdin.read())\n"
    )
    crossref_script.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PYTHONPATH"] = str(repo_root)
    env["PYDIFFTOOLS_FAKE_MATHJAX"] = "1"
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
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "tex" / "sample.tex"
    target = tmp_path / "example.tex"
    target.write_text(sample.read_text())
    cmd = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "tex2qmd",
        str(target),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp_path)
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
    proc_init = subprocess.run(cmd_init, capture_output=True, text=True, env=env)
    assert proc_init.returncode == 0
    mathjax = project_dir / "_template" / "mathjax" / "es5" / "tex-mml-chtml.js"
    assert mathjax.exists()
    cmd_build = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "qmdb",
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
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "md" / "sample.md"
    target = tmp_path / "sample.md"
    target.write_text(sample.read_text())
    cmd_extract = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "xomd",
        str(target),
    ]
    proc_extract = subprocess.run(cmd_extract, capture_output=True, text=True, env=env)
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
    proc_reorder = subprocess.run(cmd_reorder, capture_output=True, text=True, env=env)
    assert proc_reorder.returncode == 0
    content = target.read_text()
    assert content.index("## Second Topic") < content.index("## First Topic")
    assert "##### Hidden Notes" in content


def test_cpb_hides_low_headers(tmp_path):
    env = _make_cli_env(tmp_path)
    markdown_file = tmp_path / "notes.md"
    markdown_file.write_text("# Visible\n\n##### Hidden Header\nBody text.\n")
    (tmp_path / "references.bib").write_text("")
    (tmp_path / "style.csl").write_text("")
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
