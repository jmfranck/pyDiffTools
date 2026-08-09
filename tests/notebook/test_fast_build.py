import base64
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path

import pytest
import yaml

import pydifftools.notebook.fast_build as fast_build


@pytest.fixture
def fb(tmp_path, monkeypatch):
    path_names = (
        "PROJECT_ROOT",
        "BUILD_DIR",
        "DISPLAY_DIR",
        "BODY_TEMPLATE",
        "PANDOC_TEMPLATE",
        "NAV_TEMPLATE",
        "MATHJAX_DIR",
    )
    original_paths = {
        name: getattr(fast_build, name) for name in path_names
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYDIFFTOOLS_FAKE_MATHJAX", "1")
    fast_build.qmdinit(tmp_path, force=True)
    monkeypatch.setattr(
        fast_build, "load_bibliography_csl", lambda: (None, None)
    )
    try:
        yield fast_build
    finally:
        for name, value in original_paths.items():
            setattr(fast_build, name, value)


def test_load_bibliography_csl_reads_project_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("_quarto.yml").write_text(
        "project:\n"
        "  type: website\n"
        "  bibliography: references.bib\n"
        '  csl: "emails/superscript_ref_short.csl"\n'
        "  render:\n"
        "    - notebook260417.qmd\n"
    )

    assert fast_build.load_bibliography_csl() == (
        "references.bib",
        "emails/superscript_ref_short.csl",
    )


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


def test_include_falls_back_to_quarto_project_root(fb):
    nested = Path("nested/deep")
    nested.mkdir(parents=True, exist_ok=True)
    root_file = nested / "root.qmd"
    root_file.write_text("{{< include shared.qmd >}}")
    Path("shared.qmd").write_text("project root include")

    tree, roots, included_by = fb.analyze_includes([root_file.as_posix()])

    assert tree[root_file.as_posix()] == ["shared.qmd"]
    assert included_by["shared.qmd"] == [root_file.as_posix()]
    assert roots[root_file.as_posix()] == fb.PROJECT_ROOT
    assert roots["shared.qmd"] == fb.PROJECT_ROOT


def test_include_prefers_including_file_directory(fb):
    nested = Path("nested/current")
    nested.mkdir(parents=True, exist_ok=True)
    root_file = nested / "root.qmd"
    local_include = nested / "shared.qmd"
    root_file.write_text("{{< include shared.qmd >}}")
    local_include.write_text("local include")
    Path("shared.qmd").write_text("project root include")

    tree, _, included_by = fb.analyze_includes([root_file.as_posix()])

    assert tree[root_file.as_posix()] == [local_include.as_posix()]
    assert included_by[local_include.as_posix()] == [root_file.as_posix()]


def test_missing_include_error(fb, tmp_path):
    src = tmp_path / "root.qmd"
    src.write_text("{{< include missing.qmd >}}")
    with pytest.raises(FileNotFoundError):
        fb.analyze_includes([src.as_posix()])


def test_build_all_includes(fb, monkeypatch):
    def execute(blocks, **_kwargs):
        outputs = {}
        codes = {}
        for src, cells in blocks.items():
            for index, (code, *_rest) in enumerate(cells, start=1):
                outputs[(src, index)] = "<pre>TEST_OUTPUT</pre>"
                codes[(src, index)] = code
        return outputs, codes

    monkeypatch.setattr(fb, "execute_code_blocks", execute)
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


def test_render_file_paths_are_rooted_at_build_dir(fb, monkeypatch):
    (fb.PROJECT_ROOT / "references.bib").write_text(
        "@misc{dummy, title={Dummy}}\n"
    )
    csl_dir = fb.PROJECT_ROOT / "emails"
    csl_dir.mkdir()
    (csl_dir / "superscript_ref_short.csl").write_text(
        '<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    nested = fb.BUILD_DIR / "project1" / "subproject1"
    nested.mkdir(parents=True, exist_ok=True)
    (fb.BUILD_DIR / "obs.lua").write_text("")
    (nested / "tasks.qmd").write_text("# Nested\n")
    called = {}

    def fake_run(cmd, check, cwd=None, capture_output=False):
        called["args"] = cmd
        called["cwd"] = cwd

    monkeypatch.setattr(fb.subprocess, "run", fake_run)
    fb.render_file(
        Path("project1/subproject1/tasks.qmd"),
        nested / "tasks.qmd",
        fragment=True,
        bibliography="references.bib",
        csl="emails/superscript_ref_short.csl",
        webtex=True,
    )

    args = called["args"]
    assert called["cwd"] == fb.BUILD_DIR.resolve()
    assert args[1] == "project1/subproject1/tasks.qmd"
    assert args[args.index("--lua-filter") + 1] == "obs.lua"
    resource_paths = args[args.index("--resource-path") + 1].split(os.pathsep)
    assert "project1/subproject1" in resource_paths
    assert "." in resource_paths
    assert args[args.index("--template") + 1] == "../_template/body-only.html"
    assert args[args.index("--bibliography") + 1] == "../references.bib"
    assert (
        args[args.index("--csl") + 1] == "../emails/superscript_ref_short.csl"
    )
    assert args[args.index("-o") + 1] == "project1/subproject1/tasks.html"


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


def test_notebook_source_collapses_by_default(fb, tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<html><body>"
        '<div data-script="doc.qmd" data-index="1"></div>'
        "</body></html>"
    )

    fb.substitute_code_placeholders(
        page,
        {("doc.qmd", 1): "<pre>RESULT</pre>"},
        {("doc.qmd", 1): "print('hello')"},
    )

    html = page.read_text()
    assert '<details class="pydifft-source"><summary>SOURCE</summary>' in html
    assert '<div class="highlight"><pre>' in html
    assert "RESULT" in html


def test_notebook_source_display_modes(fb, tmp_path):
    always_page = tmp_path / "always.html"
    always_page.write_text(
        "<html><body>"
        '<div data-script="doc.qmd" data-index="1"></div>'
        "</body></html>"
    )
    fb.substitute_code_placeholders(
        always_page,
        {("doc.qmd", 1): "<pre>RESULT</pre>"},
        {("doc.qmd", 1): "print('hello')"},
        code_display=fb.CODE_DISPLAY_ALWAYS,
    )
    always_html = always_page.read_text()
    assert "pydifft-source" not in always_html
    assert '<div class="highlight"><pre>' in always_html
    assert "RESULT" in always_html

    no_code_page = tmp_path / "no_code.html"
    no_code_page.write_text(
        "<html><body>"
        '<div data-script="doc.qmd" data-index="1"></div>'
        "</body></html>"
    )
    fb.substitute_code_placeholders(
        no_code_page,
        {("doc.qmd", 1): "<pre>RESULT</pre>"},
        {("doc.qmd", 1): "print('hello')"},
        code_display=fb.CODE_DISPLAY_NONE,
    )
    no_code_html = no_code_page.read_text()
    assert "pydifft-source" not in no_code_html
    assert '<div class="highlight"><pre>' not in no_code_html
    assert "print" not in no_code_html
    assert "RESULT" in no_code_html


def test_no_code_empty_output_is_not_pending(fb, tmp_path):
    page = tmp_path / "empty_result.html"
    page.write_text(
        "<html><body>"
        '<div data-script="doc.qmd" data-index="1"></div>'
        "</body></html>"
    )

    fb.substitute_code_placeholders(
        page,
        {("doc.qmd", 1): ""},
        {("doc.qmd", 1): "print('quiet')"},
        code_display=fb.CODE_DISPLAY_NONE,
    )

    html = page.read_text()
    assert 'data-output-state="complete"' in html
    assert not fb.notebook_marker_is_pending("doc.qmd", html)


def test_outputs_to_html_prefers_markdown_over_plain(fb):
    html = fb.outputs_to_html(
        [
            {
                "output_type": "display_data",
                "data": {
                    "text/plain": "<IPython.core.display.Markdown object>",
                    "text/markdown": "## Generated\n\n$x$",
                },
            }
        ],
        source="doc.qmd",
    )

    assert "<IPython.core.display.Markdown object>" not in html
    assert "<h2" in html
    assert "Generated" in html
    assert "math inline" in html


def test_nb_capture_auto_import_after_reset_orders_outputs(fb):
    code = (
        "%reset -f\n"
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "fig1, ax1 = plt.subplots()\n"
        "ax1.plot([0, 1], [0, 1])\n"
        "fig2, ax2 = plt.subplots()\n"
        "ax2.plot([0, 1], [1, 0])\n"
        "with nb_capture() as out:\n"
        "    out.md('## Intro')\n"
        "    out.fig(fig1)\n"
        "    out.md('## Between')\n"
        "    out.fig(fig2)\n"
    )

    outputs, code_map = fb.execute_code_blocks(
        {"capture_test.qmd": [(code, "capture-md5", False)]}
    )

    html = outputs[("capture_test.qmd", 1)]
    first_image = html.find("data:image/png;base64")
    second_image = html.find("data:image/png;base64", first_image + 1)
    assert "Intro" in html
    assert "Between" in html
    assert html.count("data:image/png;base64") == 2
    assert html.find("Intro") < first_image
    assert first_image < html.find("Between")
    assert html.find("Between") < second_image
    assert fb.NB_CAPTURE_IMPORT not in code_map[("capture_test.qmd", 1)]


def test_generated_markdown_output_renders_in_build(fb):
    qmd = Path("generated_markdown.qmd")
    qmd.write_text(
        "# Generated markdown test\n\n"
        "```{python}\n"
        "from IPython.display import display, Markdown\n"
        "display(Markdown('## Generated\\n\\n$x$'))\n"
        "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["generated_markdown.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()

    html_path = Path("_display/generated_markdown.html")
    html = html_path.read_text()

    assert "Running notebook" not in html
    assert "<IPython.core.display.Markdown object>" not in html
    assert '<h2 id="generated">Generated</h2>' in html
    assert "math inline" in html


def test_markdown_image_next_to_source_is_embedded(fb):
    nested = Path("image_case")
    nested.mkdir()
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    (nested / "filename.png").write_bytes(png_bytes)
    (nested / "page.qmd").write_text("# Image\n\n![](filename.png)\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["image_case/page.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()

    html = Path("_display/image_case/page.html").read_text()
    assert "data:image/png;base64" in html
    assert 'src="filename.png"' not in html
    assert "src='filename.png'" not in html


def test_markdown_image_can_embed_from_build_or_display(fb):
    nested = Path("image_locations")
    nested.mkdir()
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    build_image = Path("_build/image_locations/from_build.png")
    display_image = Path("_display/image_locations/from_display.png")
    build_image.parent.mkdir(parents=True)
    display_image.parent.mkdir(parents=True)
    build_image.write_bytes(png_bytes)
    display_image.write_bytes(png_bytes)
    (nested / "page.qmd").write_text(
        "# Image locations\n\n"
        "![](from_build.png)\n\n"
        "![](from_display.png)\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["image_locations/page.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()

    html = Path("_display/image_locations/page.html").read_text()
    assert html.count("data:image/png;base64") == 2
    assert "from_build.png" not in html
    assert "from_display.png" not in html


def test_deleted_staged_qmd_forces_rebuild(fb):
    qmd = Path("force_stage.qmd")
    qmd.write_text("# Force stage\n\nContent\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["force_stage.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()

    staged_qmd = Path("_build/force_stage.qmd")
    assert staged_qmd.exists()
    staged_qmd.unlink()

    fb.build_all()

    assert staged_qmd.exists()


def test_dev_server_handler_disables_conditional_cache(fb, monkeypatch):
    handler = fb.NoCacheHTTPRequestHandler.__new__(
        fb.NoCacheHTTPRequestHandler
    )
    handler.headers = Message()
    handler.headers["If-Modified-Since"] = "Tue, 14 Nov 2023 22:13:20 GMT"
    handler.headers["If-None-Match"] = '"stale"'

    def fake_send_head(self):
        assert "If-Modified-Since" not in self.headers
        assert "If-None-Match" not in self.headers
        return "fresh body"

    monkeypatch.setattr(
        fb.SimpleHTTPRequestHandler, "send_head", fake_send_head
    )
    assert handler.send_head() == "fresh body"

    sent_headers = []
    handler.send_header = lambda name, value: sent_headers.append(
        (name, value)
    )
    monkeypatch.setattr(
        fb.SimpleHTTPRequestHandler, "end_headers", lambda self: None
    )
    handler.end_headers()

    assert (
        "Cache-Control",
        "no-store, no-cache, must-revalidate, max-age=0",
    ) in sent_headers
    assert ("Pragma", "no-cache") in sent_headers
    assert ("Expires", "0") in sent_headers


def test_navigation_persists_after_notebook_updates(fb, monkeypatch):
    qmd = Path("navigation_update.qmd")
    qmd.write_text("# Navigation update\n\n```python\nprint('one')\n```\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    config["project"]["render"] = [qmd.as_posix()]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    def execute(blocks, progress_callback=None, **_kwargs):
        src = next(iter(blocks))
        html = "<pre>INITIAL_OUTPUT</pre>"
        code = "print('one')"
        progress_callback(src, 1, 1, "running")
        progress_callback(
            src, 1, 1, "complete", html=html, code=code
        )
        return {(src, 1): html}, {(src, 1): code}

    monkeypatch.setattr(fb, "execute_code_blocks", execute)
    fb.build_all()
    render_files = fb.load_rendered_files()
    target = Path("_display/navigation_update.html")
    assert "on-this-page" in target.read_text()

    tree, _, include_map = fb.analyze_includes(render_files)
    graph = fb.RenderNotebook(render_files, tree, include_map)
    graph.mark_rendered(qmd.as_posix())
    graph.record_notebook_cell(
        qmd.as_posix(), 1, "<pre>UPDATED_OUTPUT</pre>", "print('two')"
    )
    graph.apply_notebook_outputs(
        [qmd.as_posix()], {qmd.as_posix()}, None
    )

    html = target.read_text()
    assert "UPDATED_OUTPUT" in html
    assert "on-this-page" in html


def test_refresh_callback_never_sees_menu_less_page(fb, monkeypatch):
    qmd = Path("menu_guard.qmd")
    qmd.write_text(
        "# Menu guard\n\n" "```{python}\n" "print('menu guard')\n" "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["menu_guard.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    def execute(blocks, progress_callback=None, **_kwargs):
        src = next(iter(blocks))
        html = "<pre>MENU_GUARD_OUTPUT</pre>"
        code = "print('menu guard')"
        progress_callback(src, 1, 1, "running")
        progress_callback(
            src, 1, 1, "complete", html=html, code=code
        )
        return {(src, 1): html}, {(src, 1): code}

    monkeypatch.setattr(fb, "execute_code_blocks", execute)

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


def test_incremental_navigation_only_rewrites_affected_pages(fb, monkeypatch):
    render_files = ["first.qmd", "second.qmd"]
    for qmd in render_files:
        Path(qmd).write_text(f"# {qmd}\n")
        html = (fb.DISPLAY_DIR / qmd).with_suffix(".html")
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text("<html><body></body></html>")

    graph = fb.RenderNotebook(render_files, {}, {})
    updated = []
    monkeypatch.setattr(
        fb,
        "add_navigation",
        lambda _html, _pages, current: updated.append(current),
    )

    graph.refresh_navigation({"first.qmd"})

    assert updated == ["first.qmd"]


def test_pandoc_failure_is_propagated(fb, monkeypatch):
    Path("broken.qmd").write_text("# Broken\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    config["project"]["render"] = ["broken.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))
    monkeypatch.setattr(fb, "ensure_pandoc_available", lambda: None)
    monkeypatch.setattr(fb, "ensure_pandoc_crossref", lambda: None)

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("pandoc exploded")

    monkeypatch.setattr(fb, "render_file", fail_render)

    with pytest.raises(RuntimeError, match="pandoc exploded"):
        fb.build_all()

    checksums = Path("_build/checksums.json")
    assert not checksums.exists() or "broken.qmd" not in checksums.read_text()


def test_pandoc_failure_does_not_leave_notebook_writer(fb, monkeypatch):
    Path("failed_with_notebook.qmd").write_text(
        "# Broken\n\n```python\nprint('notebook')\n```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    config["project"]["render"] = ["failed_with_notebook.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))
    notebook_started = threading.Event()
    pandoc_failed = threading.Event()
    release_notebook = threading.Event()

    def execute(*_args, **_kwargs):
        notebook_started.set()
        assert release_notebook.wait(5)
        return {}, {}

    def fail_render(*_args, **_kwargs):
        pandoc_failed.set()
        raise RuntimeError("pandoc exploded")

    monkeypatch.setattr(fb, "ensure_pandoc_available", lambda: None)
    monkeypatch.setattr(fb, "ensure_pandoc_crossref", lambda: None)
    monkeypatch.setattr(fb, "execute_code_blocks", execute)
    monkeypatch.setattr(fb, "render_file", fail_render)

    pool = ThreadPoolExecutor(max_workers=1)
    build_future = pool.submit(fb.build_all)
    try:
        assert notebook_started.wait(5)
        assert pandoc_failed.wait(5)
        assert not build_future.done()
    finally:
        release_notebook.set()
    try:
        with pytest.raises(RuntimeError, match="pandoc exploded"):
            build_future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_quarto_config_change_rebuilds_every_graph_file(fb, monkeypatch):
    rendered = []

    def fake_render_file(
        src,
        dest,
        fragment,
        bibliography=None,
        csl=None,
        webtex=False,
    ):
        rendered.append(src.as_posix())
        output = dest.with_suffix(".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "<html><head></head><body>"
            f"<p>{src.as_posix()}</p>"
            "</body></html>"
        )

    monkeypatch.setattr(fb, "ensure_pandoc_available", lambda: None)
    monkeypatch.setattr(fb, "ensure_pandoc_crossref", lambda: None)
    monkeypatch.setattr(fb, "render_file", fake_render_file)

    Path("root.qmd").write_text(
        "# Root\n\n" "{{< include child.qmd >}}\n\n" "@sec:child\n"
    )
    Path("child.qmd").write_text("## Child {#sec:child}\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["root.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    fb.build_all()
    rendered.clear()

    config["project"]["render"] = ["root.qmd", "child.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))
    fb.build_all(changed_paths=["_quarto.yml"])

    assert set(rendered) == {"root.qmd", "child.qmd"}


def test_render_tree_lists_missing_trunk_from_quarto_config(fb):
    Path("present.qmd").write_text("# Present\n")
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["missing.qmd", "present.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    render_files = fb.load_rendered_files()
    tree, _, include_map = fb.analyze_includes(render_files)
    graph = fb.RenderNotebook(render_files, tree, include_map)

    tree_text = str(graph)
    assert "missing.qmd" in tree_text
    assert "present.qmd" in tree_text


def test_code_block_counter_accepts_plain_python_fences(fb):
    text = """```python
print('hello')
```
"""
    assert fb.RenderNotebook.count_code_blocks(text) == 1


# TODO ☐: I really disapprove of calling things "monkeypatch" without further
#         explanation
def test_noexec_magic_marks_block_without_execution(fb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = Path("doc.qmd")
    src.write_text(
        "# noexec test\n\n" "```python\n" "%noexec\n" "print('skip')\n" "```\n"
    )
    fb.PROJECT_ROOT = tmp_path
    fb.BUILD_DIR = tmp_path / "_build"
    fb.BUILD_DIR.mkdir(parents=True, exist_ok=True)

    code_blocks = fb.mirror_and_modify(["doc.qmd"], {}, {"doc.qmd": tmp_path})

    assert code_blocks["doc.qmd"][0][2]
    outputs, code_map = fb.execute_code_blocks(code_blocks)
    assert "code skipped (%noexec)" in outputs[("doc.qmd", 1)]
    assert "%noexec" in code_map[("doc.qmd", 1)]


def test_notebook_progress_callback_and_kernel_environment(fb, monkeypatch):
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
        fb.ProgressExecutePreprocessor,
        "reset_execution_trackers",
        lambda self: None,
    )
    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor,
        "_check_assign_resources",
        lambda self, resources: setattr(self, "resources", resources),
    )
    def setup_kernel(preprocessor, **kwargs):
        captured["env"] = kwargs["env"]
        return DummySetupKernel(preprocessor)

    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor, "setup_kernel", setup_kernel
    )
    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor,
        "wait_for_reply",
        lambda self, reply: {"content": {"language_info": {}}},
    )
    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor,
        "preprocess_cell",
        lambda self, cell, resources, index: None,
    )
    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor,
        "set_widgets_metadata",
        lambda self: None,
    )

    nb = fb.nbformat.v4.new_notebook()
    nb.cells = [fb.nbformat.v4.new_code_cell("print('A')")]
    captured = {}
    events = []
    ep = fb.ProgressExecutePreprocessor()
    ep.cell_callback = lambda state, index, _cell: events.append(
        (state, index)
    )
    ep.preprocess(
        nb,
        {
            "metadata": {
                "source": "split_notebook.qmd",
                "notebook_index": 1,
            }
        },
    )

    assert events == [("running", 0), ("complete", 0)]
    assert captured["env"]["PYDEVD_DISABLE_FILE_VALIDATION"] == "1"


def test_execute_code_blocks_uses_project_root_cache_dir(
    fb, tmp_path, monkeypatch
):
    other_cwd = tmp_path / "other_cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    captured = {}

    def fake_preprocess(self, nb, resources=None, km=None):
        captured["path"] = resources["metadata"]["path"]
        return nb, resources

    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor,
        "preprocess",
        fake_preprocess,
    )

    fb.execute_code_blocks({"cache_path.qmd": [("print('cache')", "md5")]})

    project_cache = fb.PROJECT_ROOT / "_nbcache"
    assert captured["path"] == str(fb.PROJECT_ROOT)
    assert project_cache.exists()
    assert list(project_cache.glob("*.ipynb"))
    assert not (other_cwd / "_nbcache").exists()


def test_reset_chunks_reuse_cache_independently(fb, monkeypatch):
    events = []

    def fake_preprocess(self, nb, resources=None, km=None):
        for index, cell in enumerate(nb.cells):
            self.cell_callback("running", index, cell)
            cell.outputs = [
                fb.nbformat.v4.new_output(
                    output_type="stream", name="stdout", text="done\n"
                )
            ]
            self.cell_callback("complete", index, cell)
        return nb, resources

    monkeypatch.setattr(
        fb.ProgressExecutePreprocessor, "preprocess", fake_preprocess
    )
    original = {
        "split.qmd": [
            ("print('first')", "first-hash", False),
            ("%reset -f\nprint('second')", "second-hash", False),
        ]
    }
    fb.execute_code_blocks(original)

    changed = {
        "split.qmd": [
            ("print('first')", "first-hash", False),
            ("%reset -f\nprint('changed')", "changed-hash", False),
        ]
    }
    fb.execute_code_blocks(
        changed,
        progress_callback=(
            lambda src, notebook, cell, state, **kwargs: events.append(
                (src, notebook, cell, state)
            )
        ),
    )

    assert ("split.qmd", 1, 1, "cached") in events
    assert ("split.qmd", 1, 1, "running") not in events
    assert ("split.qmd", 2, 2, "running") in events
    assert ("split.qmd", 2, 2, "complete") in events


def test_tree_shows_notebook_cell_states_on_source_line(fb):
    qmd = Path("tree_notebooks.qmd")
    qmd.write_text(
        "```python\nprint('one')\n```\n"
        "```python\nprint('two')\n```\n"
        "```python\n%reset -f\nprint('three')\n```\n"
    )
    graph = fb.RenderNotebook(
        [qmd.as_posix()], {qmd.as_posix(): []}, {}
    )
    graph.notebook_progress(qmd.as_posix(), 1, 1, "complete", cached=True)
    graph.notebook_progress(qmd.as_posix(), 1, 2, "running")

    tree = str(graph)
    assert re.search(r"n\.b\. #1\(✓… \d{1,2}:\d{2}:\d{2}\.\d{2}\)", tree)
    assert "n.b. #2(✗)" in tree
    assert "\n    n.b." not in tree

    graph.notebook_progress(qmd.as_posix(), 2, 3, "complete", cached=True)
    assert "n.b. #2(✓ cached)" in str(graph)


def test_tree_does_not_mark_changed_cell_complete_from_old_html(fb):
    qmd = Path("changed_cell.qmd")
    old_code = "print('old')\n"
    qmd.write_text(f"```python\n{old_code}```\n")
    old_hash = fb.hashlib.md5(old_code.encode()).hexdigest()
    staged = Path("_build/changed_cell.html")
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(
        '<div data-script="changed_cell.qmd" data-index="1" '
        f'data-md5="{old_hash}" data-output-state="complete">old</div>'
    )
    qmd.write_text("```python\nprint('new')\n```\n")

    graph = fb.RenderNotebook([qmd.as_posix()], {qmd.as_posix(): []}, {})

    assert "n.b. #1(✗)" in str(graph)


def test_notebook_cells_replace_placeholders_incrementally(
    fb, monkeypatch
):
    first_complete = threading.Event()
    finish_second = threading.Event()

    def streaming_execute(blocks, progress_callback=None, **_kwargs):
        outputs = {}
        codes = {}
        src = next(iter(blocks))
        for index, marker in [(1, "FIRST_OUTPUT"), (2, "SECOND_OUTPUT")]:
            progress_callback(src, 1, index, "running")
            outputs[(src, index)] = f"<pre>{marker}</pre>"
            codes[(src, index)] = f"print('{marker}')"
            progress_callback(
                src,
                1,
                index,
                "complete",
                html=outputs[(src, index)],
                code=codes[(src, index)],
            )
            if index == 1:
                first_complete.set()
                assert finish_second.wait(5)
        return outputs, codes

    monkeypatch.setattr(fb, "execute_code_blocks", streaming_execute)
    Path("incremental.qmd").write_text(
        "# Incremental\n\n"
        "```python\nprint('first')\n```\n\n"
        "```python\nprint('second')\n```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    config["project"]["render"] = ["incremental.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    pool = ThreadPoolExecutor(max_workers=1)
    build_future = pool.submit(fb.build_all)
    try:
        assert first_complete.wait(5)
        display = Path("_display/incremental.html")
        deadline = time.time() + 5
        partial = ""
        while time.time() < deadline:
            if display.exists():
                partial = display.read_text()
                if (
                    "FIRST_OUTPUT" in partial
                    and "Running notebook" in partial
                ):
                    break
            time.sleep(0.1)
        assert "FIRST_OUTPUT" in partial
        assert "SECOND_OUTPUT" not in partial
        assert "Running notebook" in partial
    finally:
        finish_second.set()
    try:
        build_future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)

    final = display.read_text()
    assert "FIRST_OUTPUT" in final
    assert "SECOND_OUTPUT" in final
    assert "Running notebook" not in final


def test_pending_placeholder_forces_stage_rebuild_when_stage_is_empty(
    fb, capsys, monkeypatch
):
    # Build once so checksums reflect a clean tree.
    qmd = Path("async_pending.qmd")
    qmd.write_text(
        "# Async pending test\n\n"
        "```{python}\n"
        "print('async pending done')\n"
        "```\n"
    )
    config = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" not in config:
        config["project"] = {}
    config["project"]["render"] = ["async_pending.qmd"]
    Path("_quarto.yml").write_text(yaml.safe_dump(config))

    execution_count = 0

    def execute(blocks, progress_callback=None, **_kwargs):
        nonlocal execution_count
        execution_count += 1
        src = next(iter(blocks))
        marker = (
            "INITIAL_OUTPUT"
            if execution_count == 1
            else "PENDING_REBUILD_OUTPUT"
        )
        html = f"<pre>{marker}</pre>"
        code = "print('async pending done')"
        progress_callback(src, 1, 1, "running")
        progress_callback(
            src, 1, 1, "complete", html=html, code=code
        )
        return {(src, 1): html}, {(src, 1): code}

    monkeypatch.setattr(fb, "execute_code_blocks", execute)
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

    fb.build_all()

    logs = capsys.readouterr().out
    assert "Build tree:" in logs
    assert "n.b. #1(" in logs
    assert "Build plan:" not in logs
    assert "Executing cell" not in logs
    assert "Generating notebook" not in logs

    build_html = Path("_build/async_pending.html").read_text()
    display_html = Path("_display/async_pending.html").read_text()

    assert execution_count == 2
    assert "PENDING_REBUILD_OUTPUT" in build_html
    assert "PENDING_REBUILD_OUTPUT" in display_html
    assert "Running notebook" not in build_html
    assert "Running notebook" not in display_html
    assert "on-this-page" in display_html


def test_render_notebook_status_tags_and_tree_output(fb, monkeypatch):
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

    def execute(blocks, progress_callback=None, **_kwargs):
        src = next(iter(blocks))
        html = "<pre>STATUS_OUTPUT</pre>"
        code = "print('hello')"
        progress_callback(src, 1, 1, "running")
        progress_callback(
            src, 1, 1, "complete", html=html, code=code
        )
        return {(src, 1): html}, {(src, 1): code}

    monkeypatch.setattr(fb, "execute_code_blocks", execute)
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
