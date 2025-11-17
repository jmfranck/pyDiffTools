import os
import shutil
import subprocess
from pathlib import Path

import pytest

import pydifftools.notebook.fast_build as fast_build


@pytest.fixture
def fb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYDIFFTOOLS_FAKE_MATHJAX", "1")
    fast_build.scaffold_project(tmp_path, force=True)
    dummybin = tmp_path / "dummybin"
    dummybin.mkdir()
    for name in ("pandoc", "pandoc-crossref"):
        script = dummybin / name
        script.write_text("#!/bin/sh\ncat >/dev/null\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{dummybin}:{os.environ['PATH']}")
    fast_build.load_bibliography_csl = lambda: (None, None)
    real_run = fast_build.subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "pandoc":
            dest_idx = cmd.index("-o") + 1
            dest = Path(kwargs.get("cwd") or ".") / cmd[dest_idx]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("<html><body>stub</body></html>")
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(fast_build.subprocess, "run", fake_run)
    original_build = fast_build.BUILD_DIR
    original_display = fast_build.DISPLAY_DIR
    try:
        yield fast_build
    finally:
        fast_build.BUILD_DIR = original_build
        fast_build.DISPLAY_DIR = original_display


def test_analyze_includes_map(fb):
    render_files = fb.load_rendered_files()
    _, _, include_map = fb.analyze_includes(render_files)
    assert include_map['project1/index.qmd'] == ['projects.qmd']
    assert include_map['project1/subproject1/index.qmd'] == ['project1/index.qmd']
    assert include_map['project1/subproject1/tasks.qmd'] == ['project1/subproject1/index.qmd']
    assert include_map['project1/subproject1/tryforerror.qmd'] == ['project1/subproject1/index.qmd']


def test_root_file_same_dir_include(fb):
    nested = Path('project1/tmp_root')
    nested.mkdir(parents=True, exist_ok=True)
    root_file = nested / 'root.qmd'
    inc_file = nested / 'inc.qmd'
    root_file.write_text('{{< include inc.qmd >}}')
    inc_file.write_text('content')
    try:
        tree, _, included_by = fb.analyze_includes([root_file.as_posix()])
        rel_root = root_file.as_posix()
        rel_inc = inc_file.as_posix()
        assert tree[rel_root] == [rel_inc]
        assert included_by[rel_inc] == [rel_root]
    finally:
        root_file.unlink()
        inc_file.unlink()
        nested.rmdir()


def test_missing_include_error(fb, tmp_path):
    src = tmp_path / 'root.qmd'
    src.write_text('{{< include missing.qmd >}}')
    with pytest.raises(FileNotFoundError):
        fb.analyze_includes([src.as_posix()])


def test_build_all_includes(fb):
    shutil.rmtree('_build', ignore_errors=True)
    fb.build_all()
    assert Path('_build/project1/subproject1/tasks.html').exists()
    assert Path('_build/project1/subproject1/tryforerror.html').exists()


def test_render_file_webtex(fb, tmp_path, monkeypatch):
    fb.BUILD_DIR = tmp_path
    (tmp_path / 'obs.lua').write_text('')
    src = tmp_path / 'doc.qmd'
    src.write_text('Math $x^2$')
    dest = tmp_path / 'doc.qmd'
    called = {}

    def fake_run(cmd, check, cwd=None, capture_output=False):
        called['args'] = cmd

    monkeypatch.setattr(fb.subprocess, 'run', fake_run)
    fb.render_file(src, dest, fragment=False, webtex=True)
    assert '--webtex' in called['args']
    assert not any(a.startswith('--mathjax') for a in called['args'])


def test_postprocess_nested_includes(fb, tmp_path, monkeypatch):
    build_dir = tmp_path / 'build'
    display_dir = tmp_path / 'display'
    build_dir.mkdir()
    display_dir.mkdir()
    monkeypatch.setattr(fb, 'BUILD_DIR', build_dir)
    monkeypatch.setattr(fb, 'DISPLAY_DIR', display_dir)

    (build_dir / 'leaf.html').write_text('<div>LEAF</div>')
    (build_dir / 'child.html').write_text(
        '<div data-include="leaf.html" data-source="leaf.html"></div>'
    )
    (build_dir / 'root.html').write_text(
        '<section><div data-include="child.html" data-source="child.html"></div></section>'
    )

    target = display_dir / 'root.html'
    target.write_text((build_dir / 'root.html').read_text())

    fb.postprocess_html(target, build_dir, build_dir)
    html = target.read_text()
    assert 'LEAF' in html
    assert 'data-include' not in html
