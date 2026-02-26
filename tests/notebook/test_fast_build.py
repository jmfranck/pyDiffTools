import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml

import pydifftools.notebook.fast_build as fast_build


@pytest.fixture
def fb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYDIFFTOOLS_FAKE_MATHJAX", "1")
    fast_build.qmdinit(tmp_path, force=True)
    fast_build.load_bibliography_csl = lambda: (None, None)
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
    assert include_map["project1/index.qmd"] == ["projects.qmd"]
    assert include_map["project1/subproject1/index.qmd"] == [
        "project1/index.qmd"
    ]
    assert include_map["project1/subproject1/tasks.qmd"] == [
        "project1/subproject1/index.qmd"
    ]
    assert include_map["project1/subproject1/tryforerror.qmd"] == [
        "project1/subproject1/index.qmd"
    ]


def test_root_file_same_dir_include(fb):
    nested = Path("project1/tmp_root")
    nested.mkdir(parents=True, exist_ok=True)
    root_file = nested / "root.qmd"
    inc_file = nested / "inc.qmd"
    root_file.write_text("{{< include inc.qmd >}}")
    inc_file.write_text("content")
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
    src = tmp_path / "root.qmd"
    src.write_text("{{< include missing.qmd >}}")
    with pytest.raises(FileNotFoundError):
        fb.analyze_includes([src.as_posix()])


def test_build_all_includes(fb):
    shutil.rmtree("_build", ignore_errors=True)
    fb.build_all()
    assert Path("_build/project1/subproject1/tasks.html").exists()
    assert Path("_build/project1/subproject1/tryforerror.html").exists()


def test_render_file_webtex(fb, tmp_path, monkeypatch):
    fb.BUILD_DIR = tmp_path
    (tmp_path / "obs.lua").write_text("")
    src = tmp_path / "doc.qmd"
    src.write_text("Math $x^2$")
    dest = tmp_path / "doc.qmd"
    called = {}

    def fake_run(cmd, check, cwd=None, capture_output=False):
        called["args"] = cmd

    monkeypatch.setattr(fb.subprocess, "run", fake_run)
    fb.render_file(src, dest, fragment=False, webtex=True)
    assert "--webtex" in called["args"]
    assert not any(a.startswith("--mathjax") for a in called["args"])


def test_postprocess_nested_includes(fb, tmp_path, monkeypatch):
    build_dir = tmp_path / "build"
    display_dir = tmp_path / "display"
    build_dir.mkdir()
    display_dir.mkdir()
    monkeypatch.setattr(fb, "BUILD_DIR", build_dir)
    monkeypatch.setattr(fb, "DISPLAY_DIR", display_dir)

    (build_dir / "leaf.html").write_text("<div>LEAF</div>")
    (build_dir / "child.html").write_text(
        '<div data-include="leaf.html" data-source="leaf.html"></div>'
    )
    (build_dir / "root.html").write_text(
        '<section><div data-include="child.html"'
        ' data-source="child.html"></div></section>'
    )

    target = display_dir / "root.html"
    target.write_text((build_dir / "root.html").read_text())

    fb.postprocess_html(target, build_dir, build_dir)
    html = target.read_text()
    assert "LEAF" in html
    assert "data-include" not in html


def test_postprocess_adds_shared_pygments_stylesheet_link(fb, tmp_path):
    build_dir = tmp_path / "build"
    display_dir = tmp_path / "display"
    build_dir.mkdir()
    display_dir.mkdir()

    page = display_dir / "index.html"
    page.write_text(
        "<html><head></head><body>"
        '<div class="highlight"><pre>'
        '<span class="k">print</span>'
        "</pre></div>"
        "</body></html>"
    )

    fb.postprocess_html(page, build_dir, display_dir)

    html = page.read_text()
    assert 'href="assets/pygments.css"' in html
    css = (display_dir / "assets" / "pygments.css").read_text()
    assert ".highlight" in css


def test_navigation_persists_after_notebook_updates(fb):
    fb.build_all()
    render_files = fb.load_rendered_files()
    assert render_files
    target = (Path("_display") / render_files[0]).with_suffix(".html")
    assert "on-this-page" in target.read_text()

    tree, _, include_map = fb.analyze_includes(render_files)
    graph = fb.RenderNotebook(render_files, tree, include_map)
    graph.record_notebook_outputs({}, {})
    graph.apply_notebook_outputs([], set(render_files), None)

    assert "on-this-page" in target.read_text()


def test_refresh_callback_never_sees_menu_less_page(fb):
    qmd = Path("menu_guard.qmd")
    qmd.write_text(
        "# Menu guard\n\n" "```{python}\n" "print('menu guard')\n" "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["menu_guard.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    refresh_states = []

    def refresh_callback():
        page = Path("_display/menu_guard.html")
        if page.exists():
            refresh_states.append("on-this-page" in page.read_text())

    fb.build_all(refresh_callback=refresh_callback)
    assert refresh_states
    assert all(refresh_states)


def test_all_render_targets_receive_navigation_template(fb):
    Path("first_page.qmd").write_text("# First page\n\nContent")
    Path("second_page.qmd").write_text("# Second page\n\nContent")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["first_page.qmd", "second_page.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()

    for page in ["first_page", "second_page"]:
        html = Path(f"_display/{page}.html").read_text()
        assert "on-this-page" in html


def test_code_block_counter_accepts_plain_python_fences(fb):
    text = """```python
print('hello')
```
"""
    assert fb.RenderNotebook.count_code_blocks(text) == 1


def test_noexec_magic_marks_block_without_execution(fb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = Path("doc.qmd")
    src.write_text(
        "# noexec test\n\n"
        "```python\n"
        "%noexec\n"
        "print('skip')\n"
        "```\n"
    )
    fb.PROJECT_ROOT = tmp_path
    fb.BUILD_DIR = tmp_path / "_build"
    fb.BUILD_DIR.mkdir(parents=True, exist_ok=True)

    code_blocks = fb.mirror_and_modify(["doc.qmd"], {}, {"doc.qmd": tmp_path})

    assert code_blocks["doc.qmd"][0][2]
    outputs, code_map = fb.execute_code_blocks(code_blocks)
    assert "code skipped (%noexec)" in outputs[("doc.qmd", 1)]
    assert "%noexec" in code_map[("doc.qmd", 1)]


def test_notebook_progress_message_includes_notebook_index(
    fb, capsys, monkeypatch
):
    class DummyKernel:
        def kernel_info(self):
            return None

    class DummySetupKernel:
        def __init__(self, preprocessor):
            self.preprocessor = preprocessor

        def __enter__(self):
            self.preprocessor.kc = DummyKernel()
            return self.preprocessor

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "reset_execution_trackers",
        lambda self: None,
    )
    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "_check_assign_resources",
        lambda self, resources: setattr(self, "resources", resources),
    )
    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "setup_kernel",
        lambda self: DummySetupKernel(self),
    )
    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "wait_for_reply",
        lambda self, reply: {"content": {"language_info": {}}},
    )
    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "preprocess_cell",
        lambda self, cell, resources, index: None,
    )
    monkeypatch.setattr(
        fb.LoggingExecutePreprocessor,
        "set_widgets_metadata",
        lambda self: None,
    )

    nb = fb.nbformat.v4.new_notebook()
    nb.cells = [fb.nbformat.v4.new_code_cell("print('A')")]
    ep = fb.LoggingExecutePreprocessor()
    ep.preprocess(
        nb,
        {
            "metadata": {
                "source": "split_notebook.qmd",
                "notebook_index": 1,
                "notebook_total": 2,
            }
        },
    )

    logs = capsys.readouterr().out
    assert "of notebook 1/2 from split_notebook.qmd" in logs


def test_async_notebook_outputs_replace_placeholder(fb):
    # Slow notebook execution in a controlled way so the test can reliably
    # observe the red placeholder first and then the final output.
    def delayed_execute_code_blocks(blocks):
        time.sleep(2)
        outputs = {}
        code_map = {}
        for src in blocks:
            outputs[(src, 1)] = "<pre>NOTEBOOK_OUTPUT_MARKER</pre>"
            code_map[(src, 1)] = "import time"
        return outputs, code_map

    fb.execute_code_blocks = delayed_execute_code_blocks

    qmd = Path("async_test.qmd")
    qmd.write_text(
        "# Async test\n\n"
        "```{python}\n"
        "import time\n"
        "time.sleep(2)\n"
        "print('async done')\n"
        "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    # Keep this render list focused so the test validates a single async page.
    config["project"]["render"] = ["async_test.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    # Trigger the build in the background so we can observe the placeholder
    # before notebook execution completes.
    build_thread = threading.Thread(target=fb.build_all)
    build_thread.start()

    display_file = Path("_display/async_test.html")
    # Poll the display output and require the expected sequence: placeholder
    # first, then final notebook output.
    placeholder_seen = False
    found_output = False
    deadline = time.time() + 4
    while time.time() < deadline:
        if display_file.exists():
            html = display_file.read_text()
            if "Running notebook" in html:
                placeholder_seen = True
            if placeholder_seen and "Running notebook" not in html:
                if "NOTEBOOK_OUTPUT_MARKER" in html:
                    found_output = True
                    break
        time.sleep(0.5)

    build_thread.join()

    # The build thread may finish just before the callback writes refreshed
    # output, so allow a short follow-up window to observe the final page.
    output_deadline = time.time() + 4
    while not found_output and time.time() < output_deadline:
        if display_file.exists():
            html = display_file.read_text()
            if (
                "NOTEBOOK_OUTPUT_MARKER" in html
                and "Running notebook" not in html
            ):
                found_output = True
                break
        time.sleep(0.2)

    assert placeholder_seen
    assert found_output


def test_pending_placeholder_forces_stage_rebuild_when_stage_is_empty(
    fb, capsys
):
    # Build once so checksums reflect a clean tree.
    qmd = Path("async_pending.qmd")
    qmd.write_text(
        "# Async pending test\n\n"
        "```{python}\n"
        "import time\n"
        "time.sleep(2)\n"
        "print('async pending done')\n"
        "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["async_pending.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))
    fb.build_all()

    # Simulate the failing state: stale staged/display HTML still contains a
    # pending notebook marker from a prior run.
    pending_html = (
        "<html><body>"
        '<div id="on-this-page">outline</div>'
        '<div data-script="async_pending.qmd" data-index="1"></div>'
        "</body></html>"
    )
    Path("_build/async_pending.html").write_text(pending_html)
    Path("_display/async_pending.html").write_text(pending_html)

    def delayed_execute_code_blocks(blocks):
        time.sleep(2)
        outputs = {}
        code_map = {}
        for src in blocks:
            outputs[(src, 1)] = "<pre>PENDING_REBUILD_OUTPUT</pre>"
            code_map[(src, 1)] = "import time"
        return outputs, code_map

    fb.execute_code_blocks = delayed_execute_code_blocks
    fb.build_all()

    logs = capsys.readouterr().out
    assert (
        "Build plan: 1 source file(s) to render into _build, "
        "1 display target(s) to assemble from _build." in logs
    )

    build_html = ""
    display_html = ""
    deadline = time.time() + 4
    while time.time() < deadline:
        build_html = Path("_build/async_pending.html").read_text()
        display_html = Path("_display/async_pending.html").read_text()
        build_has_output = (
            "PENDING_REBUILD_OUTPUT" in build_html
            or "NOTEBOOK_OUTPUT_MARKER" in build_html
        )
        display_has_output = (
            "PENDING_REBUILD_OUTPUT" in display_html
            or "NOTEBOOK_OUTPUT_MARKER" in display_html
        )
        if (
            build_has_output
            and display_has_output
            and "Running notebook" not in build_html
            and "Running notebook" not in display_html
        ):
            break
        time.sleep(0.2)

    assert (
        "PENDING_REBUILD_OUTPUT" in build_html
        or "NOTEBOOK_OUTPUT_MARKER" in build_html
    )
    assert (
        "PENDING_REBUILD_OUTPUT" in display_html
        or "NOTEBOOK_OUTPUT_MARKER" in display_html
    )
    assert "Running notebook" not in build_html
    assert "Running notebook" not in display_html
    assert "on-this-page" in display_html


def test_render_notebook_status_tags_and_tree_output(fb):
    # Build a one-page render target and then replace the staged html with
    # unresolved notebook placeholders and stale child html to exercise state
    # tagging.
    qmd = Path("status_tags.qmd")
    qmd.write_text(
        "# Status tags\n\n"
        "{{< include status_leaf.qmd >}}\n\n"
        "```{python}\n"
        "print('hello')\n"
        "```\n"
    )
    Path("status_leaf.qmd").write_text("leaf text")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["status_tags.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))
    fb.build_all()

    pending_html = (
        "<html><body>"
        '<div data-script="status_tags.qmd" data-index="1">'
        '<div style="color:red;font-weight:bold">'
        "Running notebook status_tags.qmd..."
        "</div></div>"
        "</body></html>"
    )
    Path("_build/status_tags.html").write_text(pending_html)
    # Simulate include html not generated yet.
    Path("_build/status_leaf.html").unlink()

    render_files = fb.load_rendered_files()
    tree, _, include_map = fb.analyze_includes(render_files)
    graph = fb.RenderNotebook(render_files, tree, include_map)
    graph.mark_outdated(fb.load_checksums())
    graph.refresh_status_tags(fb.load_checksums())

    assert graph.status_contains("status_tags.qmd", "unrun ipynb")
    assert graph.status_contains("status_tags.qmd", "waiting on include build")
    assert graph.status_contains("status_leaf.qmd", "missing html")
    tree_text = str(graph)
    assert "status_tags.qmd" in tree_text
    assert "unrun ipynb" in tree_text
    assert "waiting on include build" in tree_text
    assert "missing html" in tree_text
