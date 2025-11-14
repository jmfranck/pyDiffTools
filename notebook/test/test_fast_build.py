import importlib
import sys
import types
import shutil
import os
from pathlib import Path
import pytest


def import_fast_build():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    mj = root / '_template' / 'mathjax' / 'es5'
    (mj).mkdir(parents=True, exist_ok=True)
    (mj / 'tex-mml-chtml.js').write_text('')
    dummybin = root / 'dummybin'
    dummybin.mkdir(exist_ok=True)
    crossref = dummybin / 'pandoc-crossref'
    crossref.write_text(
        "#!/usr/bin/env python3\nimport sys, shutil; shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)"
    )
    crossref.chmod(0o755)
    os.environ['PATH'] = f"{dummybin}:{os.environ['PATH']}"
    import shutil as _shutil
    real_which = _shutil.which
    def fake_which(cmd):
        if cmd == 'pandoc-crossref':
            return str(crossref)
        return real_which(cmd)
    _shutil.which = fake_which
    selenium_stub = types.ModuleType('selenium')
    webdriver_stub = types.SimpleNamespace(
        Chrome=lambda options=None: types.SimpleNamespace(quit=lambda: None),
        ChromeOptions=lambda: types.SimpleNamespace(add_argument=lambda *a, **k: None),
    )
    selenium_stub.webdriver = webdriver_stub
    selenium_stub.common = types.SimpleNamespace(
        exceptions=types.SimpleNamespace(
            WebDriverException=Exception, NoSuchWindowException=Exception
        )
    )
    sys.modules['selenium'] = selenium_stub
    sys.modules['selenium.webdriver'] = webdriver_stub
    sys.modules['selenium.common'] = selenium_stub.common
    sys.modules['selenium.common.exceptions'] = selenium_stub.common.exceptions
    fast_build = importlib.import_module('fast_build')
    fast_build.load_bibliography_csl = lambda: (None, None)
    return fast_build


def test_analyze_includes_map():
    fb = import_fast_build()
    render_files = fb.load_rendered_files()
    _, _, include_map = fb.analyze_includes(render_files)
    assert include_map['project1/index.qmd'] == ['projects.qmd']
    assert include_map['project1/subproject1/index.qmd'] == ['project1/index.qmd']
    assert include_map['project1/subproject1/tasks.qmd'] == ['project1/subproject1/index.qmd']
    assert include_map['project1/subproject1/tryforerror.qmd'] == ['project1/subproject1/index.qmd']


def test_root_file_same_dir_include():
    fb = import_fast_build()
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


def test_missing_include_error(tmp_path):
    fb = import_fast_build()
    src = tmp_path / 'root.qmd'
    src.write_text('{{< include missing.qmd >}}')
    with pytest.raises(FileNotFoundError):
        fb.analyze_includes([src.as_posix()])


def test_build_all_includes(tmp_path):
    fb = import_fast_build()
    shutil.rmtree('_build', ignore_errors=True)
    fb.build_all()
    assert Path('_build/project1/subproject1/tasks.html').exists()
    assert Path('_build/project1/subproject1/tryforerror.html').exists()


def test_render_file_webtex(tmp_path, monkeypatch):
    fb = import_fast_build()
    fb.BUILD_DIR = tmp_path
    (tmp_path / 'obs.lua').write_text('')
    src = tmp_path / 'doc.qmd'
    src.write_text('Math $x^2$')
    dest = tmp_path / 'doc.qmd'
    called = {}

    def fake_run(cmd, check, cwd, capture_output):
        called['args'] = cmd

    monkeypatch.setattr(fb.subprocess, 'run', fake_run)
    fb.render_file(src, dest, fragment=False, webtex=True)
    assert '--webtex' in called['args']
    assert not any(a.startswith('--mathjax') for a in called['args'])


def test_postprocess_nested_includes(tmp_path, monkeypatch):
    fb = import_fast_build()
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
