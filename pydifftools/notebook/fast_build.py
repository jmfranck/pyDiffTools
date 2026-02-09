#!/usr/bin/env python3
"""Minimal build script using Pandoc instead of Quarto."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading
import shutil
import yaml
from pydifftools.command_registry import register_command
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver as Observer
from selenium import webdriver
from selenium.common.exceptions import (
    WebDriverException,
    NoSuchWindowException,
)
from jinja2 import Environment, FileSystemLoader
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
from nbconvert.preprocessors.execute import NotebookClient
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from ansi2html import Ansi2HTMLConverter

_ansi_conv = Ansi2HTMLConverter(inline=True)


def _ansi_to_html(text: str, *, default_style: str | None = None) -> str:
    """Return HTML for text that may contain ANSI escape codes."""
    html = _ansi_conv.convert(text, full=False)
    if default_style and "span class" not in html:
        html = f'<span style="{default_style}">{html}</span>'
    return f"<pre>{html}</pre>"


class LoggingExecutePreprocessor(ExecutePreprocessor):
    """Execute notebook cells with progress printed to stdout."""

    def preprocess(self, nb, resources=None, km=None):
        NotebookClient.__init__(self, nb, km)
        self.reset_execution_trackers()
        self._check_assign_resources(resources)
        cell_count = len(self.nb.cells)

        with self.setup_kernel():
            assert self.kc
            info_msg = self.wait_for_reply(self.kc.kernel_info())
            assert info_msg
            self.nb.metadata["language_info"] = info_msg["content"][
                "language_info"
            ]
            for index, cell in enumerate(self.nb.cells):
                print(
                    f"Executing cell {index + 1}/{cell_count}...", flush=True
                )
                self.preprocess_cell(cell, resources, index)
        self.set_widgets_metadata()

        return self.nb, self.resources


include_pattern = re.compile(
    r"\{\{\s*<\s*(include|embed)\s+([^>\s]+)\s*>\s*\}\}"
)
# Python code block pattern
code_pattern = re.compile(r"```\{python[^}]*\}\n(.*?)```", re.DOTALL)
# Markdown image pattern
image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(
    r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}"
)


class RenderNotebook:
    """Track trunks, branches, and leaves along with build state."""

    def __init__(self, render_files, tree, include_map):
        self.render_files = render_files
        self.tree = tree
        self.include_map = include_map
        self.nodes = {}
        self.notebook_outputs = None
        self.notebook_code_map = None
        self._build_nodes()

    def _build_nodes(self):
        for path in self.tree:
            if path not in self.nodes:
                if path in self.tree:
                    children = list(self.tree[path])
                else:
                    children = []
                if path in self.include_map:
                    parents = list(self.include_map[path])
                else:
                    parents = []
                self.nodes[path] = {
                    "type": "trunk" if path in self.render_files else "branch",
                    "children": children,
                    "parents": parents,
                    "has_notebook": False,
                    "needs_build": False,
                }
        for path in list(self.nodes.keys()):
            if (
                not self.nodes[path]["children"]
                and path not in self.render_files
            ):
                self.nodes[path]["type"] = "leaf"
            src = PROJECT_ROOT / path
            if src.exists():
                text = src.read_text()
                self.nodes[path]["has_notebook"] = bool(
                    code_pattern.search(text)
                )

    def all_paths(self):
        return list(self.nodes.keys())

    def mark_outdated(self, checksums):
        for path in self.nodes:
            src = PROJECT_ROOT / path
            if not src.exists():
                self.nodes[path]["needs_build"] = False
                continue
            new_hash = self._hash_file(src)
            if path in checksums:
                old_hash = checksums[path]
            else:
                old_hash = None
            self.nodes[path]["needs_build"] = new_hash != old_hash

    def _hash_file(self, path):
        data = path.read_bytes()
        return hashlib.md5(data).hexdigest()

    def stage_targets(self, changed_paths):
        if changed_paths:
            for path in changed_paths:
                if path in self.nodes:
                    self.nodes[path]["needs_build"] = True
                    for parent in self.nodes[path]["parents"]:
                        if parent in self.nodes:
                            self.nodes[parent]["needs_build"] = True
        return sorted([p for p, d in self.nodes.items() if d["needs_build"]])

    def update_checksums(self, checksums):
        for path, data in self.nodes.items():
            if not data["needs_build"]:
                continue
            src = PROJECT_ROOT / path
            if src.exists():
                checksums[path] = self._hash_file(src)

    def render_order(self):
        return build_order(self.render_files, self.tree)

    def refresh_if_ready(self, refresh_callback):
        """Refresh the browser if a callback was provided."""
        if refresh_callback:
            refresh_callback()

    def update_display_page(self, target):
        """Update a single display page or ensure a placeholder is present."""
        src_html = (BUILD_DIR / target).with_suffix(".html")
        dest_html = (DISPLAY_DIR / target).with_suffix(".html")
        if not src_html.exists():
            dest_html.parent.mkdir(parents=True, exist_ok=True)
            dest_html.write_text(
                "<html><body><div style='color:red;font-weight:bold'>"
                f"Waiting for pandoc on {target} to complete..."
                "</div>"
                "</body></html>"
            )
            return
        dest_html.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_html, dest_html)
        # Build includes using staged fragments and rewrite math assets to the
        # display tree that the web server presents.
        postprocess_html(dest_html, BUILD_DIR, DISPLAY_DIR)

    def apply_notebook_outputs(
        self,
        stage_files,
        display_targets,
        refresh_callback,
    ):
        """Insert stored notebook outputs and refresh display pages."""
        if self.notebook_outputs is None or self.notebook_code_map is None:
            return
        for f in stage_files:
            html_file = (BUILD_DIR / f).with_suffix(".html")
            if html_file.exists():
                substitute_code_placeholders(
                    html_file,
                    self.notebook_outputs,
                    self.notebook_code_map,
                )
        for target in sorted(display_targets):
            self.update_display_page(target)
        self.refresh_if_ready(refresh_callback)

    def record_notebook_outputs(self, outputs, code_map):
        """Store notebook outputs for later substitution into HTML."""
        self.notebook_outputs = outputs
        self.notebook_code_map = code_map

    def handle_notebook_future(
        self,
        notebook_future,
        notebook_executor,
        stage_files,
        display_targets,
        refresh_callback,
    ):
        """Record notebook outputs and refresh display pages when ready."""
        outputs, code_map = notebook_future.result()
        if notebook_executor:
            notebook_executor.shutdown(wait=False)
        self.record_notebook_outputs(outputs, code_map)
        print("Notebook execution complete; applying outputs.", flush=True)
        self.apply_notebook_outputs(
            stage_files,
            display_targets,
            refresh_callback,
        )


def load_checksums():
    path = BUILD_DIR / "checksums.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_checksums(checksums):
    path = BUILD_DIR / "checksums.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checksums, indent=2))


def load_rendered_files():
    text = Path("_quarto.yml").read_text()
    cfg = yaml.safe_load(text)
    return list(cfg.get("project", {}).get("render", []))


def load_bibliography_csl():
    text = Path("_quarto.yml").read_text()
    cfg = yaml.safe_load(text)
    bib = None
    csl = None
    if "bibliography" in cfg:
        bib = cfg["bibliography"]
    if "csl" in cfg:
        csl = cfg["csl"]
    fmt = cfg.get("format", {})
    if isinstance(fmt, dict):
        for v in fmt.values():
            if isinstance(v, dict):
                if bib is None and "bibliography" in v:
                    bib = v["bibliography"]
                if csl is None and "csl" in v:
                    csl = v["csl"]
    return bib, csl


def outputs_to_html(outputs: list[dict]) -> str:
    """Convert Jupyter cell outputs to HTML with embedded images."""
    parts = []
    for out in outputs:
        typ = out.get("output_type")
        if typ == "stream":
            text = out.get("text", "")
            parts.append(_ansi_to_html(text))
        elif typ in {"display_data", "execute_result"}:
            data = out.get("data", {})
            if "text/html" in data:
                parts.append(data["text/html"])
            elif "image/png" in data:
                src = f"data:image/png;base64,{data['image/png']}"
                parts.append(f"<img src='{src}'/>")
            elif "image/jpeg" in data:
                src = f"data:image/jpeg;base64,{data['image/jpeg']}"
                parts.append(f"<img src='{src}'/>")
            elif "text/plain" in data:
                parts.append(_ansi_to_html(data["text/plain"]))
        elif typ == "error":
            tb = "\n".join(out.get("traceback", []))
            if not tb:
                tb = f"{out.get('ename', '')}: {out.get('evalue', '')}"
            parts.append(_ansi_to_html(tb, default_style="color:red;"))
    return "\n".join(parts)


NOTEBOOK_CACHE_DIR = Path("_nbcache")


def execute_code_blocks(blocks):
    """Run code blocks as Jupyter notebooks with caching."""
    NOTEBOOK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {}
    code_map = {}
    jobs = []

    # Collect notebook chunks so we can present progress like (1/3).
    for src, cells in blocks.items():
        if not cells:
            continue
        codes = [c for c, _ in cells]
        md5s = [m for _, m in cells]
        groups = []
        current_codes = []
        current_md5s = []
        current_indices = []
        for idx, code in enumerate(codes, start=1):
            stripped = code.lstrip()
            # Split execution into separate notebooks whenever a cell
            # begins with ``%reset -f`` so that changing code after a
            # reset only reruns the affected portion instead of the entire
            # file.
            if current_codes and stripped.startswith("%reset -f"):
                groups.append((current_indices, current_codes, current_md5s))
                current_codes = []
                current_md5s = []
                current_indices = []
            current_codes.append(code)
            current_md5s.append(md5s[idx - 1])
            current_indices.append(idx)
        if current_codes:
            groups.append((current_indices, current_codes, current_md5s))

        total_groups = len(groups)
        for group_idx, data in enumerate(groups, start=1):
            jobs.append((src, total_groups, group_idx, data, codes))

    def run_job(job):
        src, total_groups, group_idx, group_data, codes = job
        group_indices, group_codes, group_md5s = group_data
        hash_input = (src + ":" + "".join(group_md5s)).encode()
        nb_hash = hashlib.md5(hash_input).hexdigest()
        nb_path = NOTEBOOK_CACHE_DIR / f"{nb_hash}.ipynb"
        if nb_path.exists():
            print(f"Reading cached output for {src} from {nb_path}!")
            nb = nbformat.read(nb_path, as_version=4)
        else:
            # Report progress with the chunk count for this source.
            print(
                f"Generating notebook ({group_idx}/{total_groups}) "
                f"for {src} at {nb_path}:"
            )
            nb = nbformat.v4.new_notebook()
            nb.cells = [nbformat.v4.new_code_cell(c) for c in group_codes]
            ep = LoggingExecutePreprocessor(
                kernel_name="python3", timeout=10800, allow_errors=True
            )
            try:
                ep.preprocess(
                    nb, {"metadata": {"path": str(Path(src).parent)}}
                )
            except Exception as e:
                tb = traceback.format_exc()
                if nb.cells:
                    nb.cells[0].outputs = [
                        nbformat.v4.new_output(
                            output_type="error",
                            ename=type(e).__name__,
                            evalue=str(e),
                            traceback=tb.splitlines(),
                        )
                    ]
                    for cell in nb.cells[1:]:
                        cell.outputs = [
                            nbformat.v4.new_output(
                                output_type="stream",
                                name="stderr",
                                text="previous cell failed to execute\n",
                            )
                        ]
            nbformat.write(nb, nb_path)

        return src, group_indices, nb, codes

    # Execute notebook chunks concurrently so long-running groups do not block.
    max_workers = max(1, min(len(jobs), 4))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(run_job, job) for job in jobs]
        for future in as_completed(futures):
            src, group_indices, nb, codes = future.result()
            for offset, cell in enumerate(nb.cells):
                html = outputs_to_html(cell.get("outputs", []))
                idx = group_indices[offset]
                outputs[(src, idx)] = html
                code_map[(src, idx)] = codes[idx - 1]

    return outputs, code_map


def analyze_includes(render_files):
    """Analyze include relationships for all render files.

    Returns a tuple ``(tree, roots, included_by)`` where:

    * ``tree`` maps each file to the files it directly includes.
    * ``roots`` maps each file to the root directory of the main document
      that ultimately includes it. This keeps include resolution consistent
      with Quarto's behavior.
    * ``included_by`` maps an included file to the files that include it.
    """

    tree: dict[str, list[str]] = {}
    included_by: dict[str, list[str]] = {}
    visited = set()

    stack = [Path(f).resolve() for f in render_files]
    root = PROJECT_ROOT
    root_dirs = {
        Path(f).resolve(): Path(f).parent.resolve() for f in render_files
    }

    while stack:
        current = stack.pop()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        root_dir = root_dirs.get(current, current.parent)
        includes: list[str] = []
        text = current.read_text()
        for _kind, inc in include_pattern.findall(text):
            target = (current.parent / inc).resolve()
            if not target.exists():
                target = (root_dir / inc).resolve()
            if not target.exists():
                target = (root_dir.parent / inc).resolve()
            if not target.exists():
                raise FileNotFoundError(
                    f"Include file '{inc}' not found for '{current}'"
                )
            try:
                rel = target.relative_to(root).as_posix()
            except ValueError:
                rel = target.as_posix()
            includes.append(rel)
            stack.append(target)
            root_dirs.setdefault(target, root_dir)
            try:
                cur_rel = current.relative_to(root).as_posix()
            except ValueError:
                cur_rel = current.as_posix()
            included_by.setdefault(rel, []).append(cur_rel)
        try:
            key = current.relative_to(root).as_posix()
        except ValueError:
            key = current.as_posix()
        tree[key] = includes

    roots_str: dict[str, Path] = {}
    for p, d in root_dirs.items():
        if not p.exists():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        roots_str[rel] = d

    return tree, roots_str, included_by


def resolve_render_file(file, included_by, render_files):
    visited = set()
    while file not in render_files:
        if file in visited or file not in included_by:
            break
        visited.add(file)
        file = included_by[file][0]
    return file


def collect_anchors(render_files, included_by):
    anchors = {}
    for path in Path(".").rglob("*.qmd"):
        if BUILD_DIR in path.parents:
            continue
        lines = path.read_text().splitlines()
        for line in lines:
            for m in anchor_pattern.finditer(line):
                kind, ident = m.group(1), m.group(2)
                key = f"{kind}:{ident}"
                text = ident
                hm = heading_pattern.match(line)
                if hm:
                    text = hm.group(2).strip()
                render_file = resolve_render_file(
                    path.as_posix(), included_by, render_files
                )
                anchors[key] = (render_file, text)
    return anchors


ref_pattern = re.compile(r"@(sec|fig|tab):([A-Za-z0-9_-]+)")


def replace_refs_text(text, anchors, dest_dir: Path):
    def repl(match):
        kind, ident = match.group(1), match.group(2)
        key = f"{kind}:{ident}"
        if key in anchors:
            file, label = anchors[key]
            html_path = BUILD_DIR / file.replace(".qmd", ".html")
            rel = os.path.relpath(html_path, dest_dir)
            link = f"{rel}#{key}"
            return f"[{label}]({link})"
        return match.group(0)

    return ref_pattern.sub(repl, text)


def replace_refs(path, anchors):
    content = path.read_text()
    new_content = replace_refs_text(content, anchors, path.parent)
    if new_content != content:
        path.write_text(new_content)
        return True
    return False


BUILD_DIR = Path("_build")
DISPLAY_DIR = Path("_display")
BODY_TEMPLATE = Path("_template/body-only.html").resolve()
PANDOC_TEMPLATE = Path("_template/pandoc_template.html").resolve()
NAV_TEMPLATE = Path("_template/nav_template.html").resolve()
MATHJAX_DIR = Path("_template/mathjax").resolve()
PROJECT_ROOT = Path(".").resolve()


def example_notebook_root():
    """Return the path to the bundled example notebook directory."""

    return Path(__file__).resolve().parents[2] / "example_notebook"


def download_mathjax(target_dir):
    """Download MathJax into ``target_dir`` if it is missing."""
    target_dir = Path(target_dir)
    script = target_dir / "es5" / "tex-mml-chtml.js"
    if script.exists():
        return
    if os.environ.get("PYDIFFTOOLS_FAKE_MATHJAX"):
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("// fake mathjax for testing")
        return
    tmp = Path("_mjtmp")
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["npm", "init", "-y"], cwd=tmp, check=True)
    subprocess.run(["npm", "install", "mathjax-full"], cwd=tmp, check=True)
    src = tmp / "node_modules" / "mathjax-full" / "es5"
    (target_dir / "es5").mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target_dir / "es5", dirs_exist_ok=True)
    shutil.rmtree(tmp)


def ensure_mathjax():
    """Ensure the default MathJax cache exists for builds."""
    download_mathjax(MATHJAX_DIR)


def _copy_resource_tree(resource, dest, overwrite=False):
    dest = Path(dest)
    if resource.is_dir():
        for child in resource.iterdir():
            _copy_resource_tree(child, dest / child.name, overwrite)
        return
    if dest.exists() and not overwrite:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resource.read_bytes())


def ensure_template_assets(project_root, overwrite=False):
    """Copy template assets from the checked-in example notebook when
    present."""

    template_src = example_notebook_root() / "_template"
    target = Path(project_root) / "_template"
    target.mkdir(parents=True, exist_ok=True)
    if template_src.exists():
        _copy_resource_tree(template_src, target, overwrite)
    # Fall back to simple built-in templates when packaged assets are missing.
    nav_target = target / "nav_template.html"
    if overwrite or not nav_target.exists():
        nav_target.write_text("""
<style>
#on-this-page {font-family: sans-serif; border: 1px solid #ddd; padding: \
0.5rem; margin-bottom: 1rem;}
#on-this-page h2 {margin-top: 0; font-size: 1.1rem;}
#on-this-page ul {list-style: none; padding-left: 0; margin: 0;}
#on-this-page li {margin: 0.25rem 0;}
</style>
<nav id="on-this-page">
  <h2>On this page</h2>
  <ul>
  {% for page in pages %}
    <li><a href="{{ page.href }}">{{ page.title or page.file }}</a></li>
  {% endfor %}
  </ul>
</nav>
            """)
    body_target = target / "body-only.html"
    if overwrite or not body_target.exists():
        body_target.write_text("""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  $for(header-includes)$
  $header-includes$
  $endfor$
</head>
<body>
$body$
</body>
</html>
            """)
    pandoc_target = target / "pandoc_template.html"
    if overwrite or not pandoc_target.exists():
        pandoc_target.write_text(body_target.read_text())
    obs_target = target / "obs.lua"
    if overwrite or not obs_target.exists():
        obs_target.write_text("-- placeholder filter\n")


def _write_placeholder_outputs():
    """Create stub HTML outputs when optional build dependencies
    are missing."""

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for qmd in PROJECT_ROOT.rglob("*.qmd"):
        rel = qmd.relative_to(PROJECT_ROOT)
        target = BUILD_DIR / rel.with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = qmd.read_text()
        except OSError:
            content = ""
        if not content:
            content = f"<html><body>{rel}</body></html>"
        target.write_text(content)


@register_command(
    "Initialize a sample Quarto project with bundled templates",
    help={
        "path": (
            "Directory to initialize (defaults to current working directory)"
        ),
        "force": "Overwrite existing files when copying the scaffold",
    },
)
def qmdinit(path, force=False):
    """Copy the example notebook contents into ``path`` for a ready-to-run
    demo."""

    if path is None:
        path = "."
    source_root = example_notebook_root()
    if not source_root.exists():
        raise RuntimeError("example_notebook directory is missing")
    target = Path(path).resolve()
    # Keep all of the key paths tied to the project we just initialized so
    # subsequent build steps read and write in the expected location even if
    # the module was imported from elsewhere.
    global PROJECT_ROOT, BUILD_DIR, DISPLAY_DIR
    global BODY_TEMPLATE, PANDOC_TEMPLATE, NAV_TEMPLATE, MATHJAX_DIR
    PROJECT_ROOT = target
    BUILD_DIR = PROJECT_ROOT / "_build"
    DISPLAY_DIR = PROJECT_ROOT / "_display"
    BODY_TEMPLATE = PROJECT_ROOT / "_template" / "body-only.html"
    PANDOC_TEMPLATE = PROJECT_ROOT / "_template" / "pandoc_template.html"
    NAV_TEMPLATE = PROJECT_ROOT / "_template" / "nav_template.html"
    MATHJAX_DIR = PROJECT_ROOT / "_template" / "mathjax"
    for child in source_root.iterdir():
        _copy_resource_tree(child, target / child.name, force)
    # Some expected render targets are not present in the checked-in example,
    # so create lightweight placeholders to keep the sample project runnable
    # in isolation.
    projects_qmd = target / "projects.qmd"
    if force or not projects_qmd.exists():
        projects_qmd.write_text("{{< include project1/index.qmd >}}\n")
    notebook_qmd = target / "notebook250708.qmd"
    if force or not notebook_qmd.exists():
        notebook_qmd.write_text("# Example notebook placeholder\n")
    ensure_template_assets(target, overwrite=force)
    download_mathjax(target / "_template" / "mathjax")
    print(f"Initialized Quarto scaffold in {target.resolve()}")


@register_command(
    "Build Quarto-style projects with Pandoc and the fast builder (optionally"
    " watch)",
    help={
        "no_browser": "Do not launch a browser when using --watch",
        "webtex": "Use Pandoc's --webtex option instead of MathJax",
    },
)
def qmdb(no_browser=False, webtex=False):
    """Build and watch the current directory using the fast notebook
    builder."""

    ensure_template_assets(Path("."))
    if yaml is None or nbformat is None or Environment is None:
        # Minimal fallback when optional dependencies are unavailable.
        _write_placeholder_outputs()
        return
    watch_and_serve(no_browser=no_browser, webtex=webtex)


def ensure_pandoc_available():
    """Make sure pandoc is discoverable on PATH."""
    if shutil.which("pandoc"):
        return
    quarto_pandoc = Path("/opt/quarto/bin/tools/x86_64/pandoc")
    if quarto_pandoc.exists():
        os.environ["PATH"] += os.pathsep + str(quarto_pandoc.parent)
    if shutil.which("pandoc"):
        return
    raise RuntimeError(
        "Pandoc not found. Install it from https://pandoc.org/installing.html"
    )


def ensure_pandoc_crossref():
    """Verify pandoc-crossref is installed for reference handling."""
    if shutil.which("pandoc-crossref"):
        return
    raise RuntimeError(
        "pandoc-crossref not found. Install it from"
        " https://github.com/lierdakil/pandoc-crossref"
    )


def all_files(render_files, tree):
    files = {f for f in render_files if Path(f).exists()}
    for src, incs in tree.items():
        if Path(src).exists():
            files.add(src)
        for inc in incs:
            if Path(inc).exists():
                files.add(inc)
    return files


def build_order(render_files, tree):
    order = []
    visited = set()

    def visit(f):
        if f in visited:
            return
        visited.add(f)
        for child in tree.get(f, []):
            visit(child)
        order.append(f)

    for f in render_files:
        visit(f)
    return order


def collect_render_targets(targets, included_by, render_files):
    """Find render files impacted by ``targets``."""
    result = set()
    stack = list(targets)
    seen = set()
    render_set = set(render_files)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in render_set:
            result.add(current)
        if current in included_by:
            for parent in included_by[current]:
                stack.append(parent)
    return result


def mirror_and_modify(files, anchors, roots):
    project_root = PROJECT_ROOT
    code_blocks: dict[str, list[tuple[str, str]]] = {}
    for file in files:
        src = Path(file)
        dest = BUILD_DIR / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        text = replace_refs_text(text, anchors, dest.parent)

        root_dir = roots.get(file, src.parent)

        def repl(match: re.Match) -> str:
            kind, inc = match.groups()
            # include paths are now relative to the main document root
            target_src = (root_dir / inc).resolve()
            if not target_src.exists():
                target_src = (src.parent / inc).resolve()
            if not target_src.exists():
                target_src = (root_dir.parent / inc).resolve()
            target_rel = target_src.relative_to(project_root)
            html_path = (BUILD_DIR / target_rel).with_suffix(".html")
            inc_path = os.path.relpath(html_path, dest.parent)
            # use an element marker preserved by Pandoc
            source_attr = target_rel.with_suffix(".html").as_posix()
            # keep track of the staged include so the display pass can load it
            return (
                f'<div data-{kind.lower()}="{inc_path}" '
                f'data-source="{source_attr}"></div>'
            )

        text = include_pattern.sub(repl, text)

        idx = 0

        def repl_code(match: re.Match) -> str:
            nonlocal idx
            idx += 1
            code = match.group(1)
            md5 = hashlib.md5(code.encode()).hexdigest()
            src_rel = str(src)
            code_blocks.setdefault(src_rel, []).append((code, md5))
            return (
                f'<div data-script="{src_rel}" data-index="{idx}"'
                f' data-md5="{md5}"></div>'
            )

        text = code_pattern.sub(repl_code, text)
        # copy referenced images into the build directory
        for img in image_pattern.findall(text):
            img_path = img.split()[0]
            if re.match(r"https?://", img_path) or img_path.startswith(
                "data:"
            ):
                continue
            target_src = (src.parent / img_path).resolve()
            if not target_src.exists():
                target_src = (root_dir / img_path).resolve()
            if not target_src.exists():
                target_src = (root_dir.parent / img_path).resolve()
            if target_src.exists():
                try:
                    rel = target_src.relative_to(project_root)
                except ValueError:
                    continue
                target_dest = BUILD_DIR / rel
                target_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_src, target_dest)
        dest.write_text(text)
    return code_blocks


def render_file(
    src: Path,
    dest: Path,
    fragment: bool,
    bibliography=None,
    csl=None,
    webtex: bool = False,
):
    """Render ``src`` to ``dest`` using Pandoc with embedded resources."""

    template = BODY_TEMPLATE if fragment else PANDOC_TEMPLATE
    temp = os.path.relpath(
        DISPLAY_DIR / "mathjax" / "es5" / "tex-mml-chtml.js", dest.parent
    )
    math_arg = (
        "--webtex" if webtex else (f"--mathjax={temp}?config=TeX-AMS_CHTML")
    )
    args = [
        "pandoc",
        src.name,
        "--from",
        "markdown+raw_html",
        "--standalone",
        "--embed-resources",
        "--lua-filter",
        os.path.relpath(BUILD_DIR / "obs.lua", dest.parent),
        "--filter",
        "pandoc-crossref",
        "--citeproc",
        math_arg,
        "--template",
        os.path.relpath(template, dest.parent),
        "-o",
        dest.with_suffix(".html").name,
    ]
    if bibliography:
        bib_path = Path(os.path.expanduser(bibliography))
        if not bib_path.is_absolute():
            bib_path = PROJECT_ROOT / bib_path
        if not bib_path.exists():
            raise FileNotFoundError(
                f"Bibliography file {bibliography} not found"
            )
        args += ["--bibliography", os.path.relpath(bib_path, dest.parent)]
    if csl:
        csl_path = Path(os.path.expanduser(csl))
        if not csl_path.is_absolute():
            csl_path = PROJECT_ROOT / csl_path
        if not csl_path.exists():
            raise FileNotFoundError(f"CSL file {csl} not found")
        args += ["--csl", os.path.relpath(csl_path, dest.parent)]
    print(f"Running pandoc on {src}...", flush=True)
    start = time.time()
    try:
        subprocess.run(args, check=True, cwd=dest.parent, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{e.stderr}\nwhen trying to run:{' '.join(args)}")
    duration = time.time() - start
    print(
        f"Finished pandoc on {src} in {duration:.1f}s",
        flush=True,
    )


try:
    from lxml import html as lxml_html
except ImportError:
    lxml_html = None


def parse_headings(html_path: Path):
    """Return a nested list of headings found in ``html_path``."""
    if lxml_html is None:
        return []
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    headings = root.xpath("//h1|//h2|//h3|//h4|//h5|//h6")

    # Skip headings used for the page title which Quarto renders with the
    # ``title`` class. Including these in the navigation duplicates the page
    # title entry in the section list.
    def is_page_title(h):
        cls = h.get("class") or ""
        return "title" in cls.split()

    headings = [h for h in headings if not is_page_title(h)]
    items: list[dict] = []
    stack = []
    for h in headings:
        level = int(h.tag[1])
        text = "".join(h.itertext()).strip()
        ident = h.get("id")
        node = {"level": level, "text": text, "id": ident, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            items.append(node)
        stack.append(node)
    return items


def read_title(qmd: Path) -> str:
    text = qmd.read_text()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end])
                if isinstance(meta, dict) and "title" in meta:
                    return str(meta["title"])
            except Exception:
                pass
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return qmd.stem


def add_navigation(html_path: Path, pages: list[dict], current: str):
    """Insert navigation menu for ``html_path`` using ``pages`` data."""
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    body = root.xpath("//body")
    if not body:
        return
    # remove any existing navigation to keep incremental updates clean
    for old in root.xpath('//*[@id="on-this-page"]'):
        parent = old.getparent()
        if parent is not None:
            parent.remove(old)
    for old in root.xpath("//style[contains(., '#on-this-page')]"):
        parent = old.getparent()
        if parent is not None:
            parent.remove(old)
    for old in root.xpath("//script[contains(., 'on-this-page')]"):
        parent = old.getparent()
        if parent is not None:
            parent.remove(old)

    env = Environment(loader=FileSystemLoader(str(NAV_TEMPLATE.parent)))
    tmpl = env.get_template(NAV_TEMPLATE.name)
    local_pages = []
    for page in pages:
        href_path = (DISPLAY_DIR / page["file"]).with_suffix(".html")
        href = os.path.relpath(href_path, html_path.parent)
        local_pages.append({**page, "href": href})
    rendered = tmpl.render(pages=local_pages, current=current)
    frags = lxml_html.fragments_fromstring(rendered)
    head = root.xpath("//head")
    head = head[0] if head else None
    for frag in frags:
        if frag.tag == "style" and head is not None:
            head.append(frag)
        else:
            body[0].insert(0, frag)
    tree.write(str(html_path), encoding="utf-8", method="html")


def postprocess_html(html_path: Path, include_root: Path, resource_root: Path):
    """Replace placeholder nodes with referenced HTML bodies."""
    root = lxml_html.fromstring(html_path.read_text())
    # keep processing until no include placeholders remain so nested includes
    # are fully expanded in the served HTML
    while True:
        nodes = list(root.xpath("//*[@data-include] | //*[@data-embed]"))
        if not nodes:
            break
        progress = False
        for node in nodes:
            target_rel = node.get("data-source")
            if not target_rel:
                target_rel = node.get("data-include") or node.get("data-embed")
            target = (include_root / target_rel).resolve()
            if target.exists():
                # announce include substitutions so the console logs which
                # staged fragments feed each served page
                try:
                    dest_rel = html_path.relative_to(DISPLAY_DIR).as_posix()
                except ValueError:
                    dest_rel = html_path.name
                print(f"including {target_rel} into {dest_rel}")
                frag_text = target.read_text()
                frag = lxml_html.fromstring(frag_text)
                body = frag.xpath("body")
                if body:
                    elems = list(body[0])
                else:
                    elems = [frag]
                parent = node.getparent()
                if parent is None:
                    continue
                idx = parent.index(node)
                parent.remove(node)
                end_c = lxml_html.HtmlComment(f"END include {target_rel}")
                start_c = lxml_html.HtmlComment(f"BEGIN include {target_rel}")
                parent.insert(idx, end_c)
                for elem in reversed(elems):
                    parent.insert(idx, elem)
                parent.insert(idx, start_c)
                progress = True
            else:
                parent = node.getparent()
                if parent is not None:
                    placeholder = lxml_html.fragment_fromstring(
                        '<div style="color:red;font-weight:bold">'
                        f"Waiting for pandoc on {target_rel} to complete..."
                        "</div>",
                        create_parent=False,
                    )
                    idx = parent.index(node)
                    parent.remove(node)
                    parent.insert(idx, placeholder)
                    progress = True
        if not progress:
            break
    # ensure MathJax references point at the provided resource root so the
    # served HTML loads scripts from the display tree instead of the staging
    # area.
    math_nodes = root.xpath(
        '//*[@class="math inline" or @class="math display"]'
    )
    if math_nodes:
        head = root.xpath("//head")
        if head:
            math_path = os.path.relpath(
                resource_root / "mathjax" / "es5" / "tex-mml-chtml.js",
                html_path.parent,
            )
            existing = root.xpath('//script[contains(@src, "MathJax")]')
            if existing:
                for node in existing:
                    node.set("src", math_path)
                    node.set("id", node.get("id") or "MathJax-script")
                    node.set("async", "")
            else:
                script = lxml_html.fragment_fromstring(
                    '<script id="MathJax-script" async'
                    f' src="{math_path}"></script>',
                    create_parent=False,
                )
                head[0].append(script)
    html_path.write_text(lxml_html.tostring(root, encoding="unicode"))


def substitute_code_placeholders(
    html_path: Path,
    outputs: dict[tuple[str, int], str],
    codes: dict[tuple[str, int], str],
) -> None:
    """Replace script placeholders in ``html_path`` using executed outputs and
    embed syntax highlighted source code.
    """
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    formatter = HtmlFormatter()
    head = root.xpath("//head")
    if head and not root.xpath('//style[@id="pygments-style"]'):
        style = formatter.get_style_defs(".highlight")
        style_node = lxml_html.fragment_fromstring(
            f'<style id="pygments-style">{style}</style>', create_parent=False
        )
        head[0].append(style_node)
    changed = False
    for node in list(root.xpath("//div[@data-script][@data-index]")):
        src = node.get("data-script")
        try:
            idx = int(node.get("data-index", "0"))
        except ValueError:
            idx = 0
        missing_output = (src, idx) not in outputs
        if missing_output:
            html = ""
        else:
            html = outputs[(src, idx)]
        if (src, idx) in codes:
            code = codes[(src, idx)]
        else:
            code = ""
        code_html = highlight(code, PythonLexer(), formatter)
        frags = lxml_html.fragments_fromstring(code_html)
        if not missing_output and html:
            frags += lxml_html.fragments_fromstring(html)
        elif missing_output:
            # Only show the placeholder when the notebook output entry is
            # absent so executed cells that intentionally produce no output
            # simply render the source code.
            waiting = lxml_html.fragment_fromstring(
                '<div style="color:red;font-weight:bold">'
                f"Running notebook {src}..."
                "</div>",
                create_parent=False,
            )
            frags.append(waiting)
        parent = node.getparent()
        if parent is None:
            continue
        pos = parent.index(node)
        parent.remove(node)
        for frag in reversed(frags):
            parent.insert(pos, frag)
        changed = True
    if changed:
        tree.write(str(html_path), encoding="utf-8", method="html")


def build_all(webtex: bool = False, changed_paths=None, refresh_callback=None):
    ensure_pandoc_available()
    ensure_pandoc_crossref()
    ensure_template_assets(PROJECT_ROOT)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DISPLAY_DIR.mkdir(parents=True, exist_ok=True)
    if not webtex:
        ensure_mathjax()
        # copy MathJax into the display tree so browsers load assets from the
        # served directory while the staging area remains limited to fragments.
        shutil.copytree(
            MATHJAX_DIR, DISPLAY_DIR / "mathjax", dirs_exist_ok=True
        )
    # copy project configuration without the render list so individual renders
    # don't attempt to build the entire project
    if yaml is not None:
        cfg = yaml.safe_load(Path("_quarto.yml").read_text())
        if "project" in cfg and "render" in cfg["project"]:
            cfg["project"]["render"] = []
        (BUILD_DIR / "_quarto.yml").write_text(yaml.safe_dump(cfg))
    else:
        # Without PyYAML, copy the config as-is so the builder can still
        # produce placeholder outputs.
        (BUILD_DIR / "_quarto.yml").write_text(Path("_quarto.yml").read_text())
    if Path("_template/obs.lua").exists():
        shutil.copy2("_template/obs.lua", BUILD_DIR / "obs.lua")

    checksums = load_checksums()

    render_files = load_rendered_files()
    bibliography, csl = load_bibliography_csl()
    tree, roots, include_map = analyze_includes(render_files)
    graph = RenderNotebook(render_files, tree, include_map)
    graph.mark_outdated(checksums)
    anchors = collect_anchors(render_files, include_map)

    if changed_paths:
        normalized = set()
        for path in changed_paths:
            candidate = Path(path)
            if not candidate.exists():
                continue
            try:
                rel = candidate.resolve().relative_to(PROJECT_ROOT)
            except ValueError:
                continue
            if rel.suffix != ".qmd":
                continue
            normalized.add(rel.as_posix())
        stage_set = set(graph.stage_targets(normalized))
        display_targets = collect_render_targets(
            stage_set, include_map, render_files
        )
        for rel in stage_set:
            if rel in render_files:
                display_targets.add(rel)
        if not stage_set and not display_targets:
            return {
                "render_files": render_files,
                "tree": tree,
                "include_map": include_map,
            }
    else:
        stage_set = set(graph.stage_targets(None))
        display_targets = set(render_files)

    stage_files = sorted(stage_set)
    # phase 1: rebuild the modified sources into the staging tree
    code_blocks = mirror_and_modify(stage_files, anchors, roots)

    # Start notebook execution immediately so it can run while pandoc renders.
    notebook_executor = None
    notebook_future = None
    outputs = {}
    code_map = {}
    if code_blocks:
        notebook_executor = ThreadPoolExecutor(max_workers=1)
        notebook_future = notebook_executor.submit(
            execute_code_blocks, code_blocks
        )

    order = graph.render_order()
    render_targets = [f for f in order if f in stage_set]
    # phase 2: ensure display pages exist right away with placeholders so
    # browsers can load content while pandoc runs.
    for target in sorted(display_targets):
        graph.update_display_page(target)
    graph.refresh_if_ready(refresh_callback)
    if render_targets:
        workers = max(1, min(len(render_targets), 4))
        tasks = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for f in render_targets:
                fragment = f not in render_files
                future = pool.submit(
                    render_file,
                    Path(f),
                    BUILD_DIR / f,
                    fragment,
                    bibliography,
                    csl,
                    webtex,
                )
                tasks.append((f, future))
            for future in as_completed([t[1] for t in tasks]):
                for pair in tasks:
                    if pair[1] is future:
                        print(f"Pandoc finished for {pair[0]}")
                        break

    graph.update_checksums(checksums)
    save_checksums(checksums)

    # phase 3: insert whatever notebook output is available into staged pages
    if notebook_future and notebook_future.done():
        graph.handle_notebook_future(
            notebook_future,
            notebook_executor,
            stage_files,
            display_targets,
            refresh_callback,
        )
        notebook_executor = None
        notebook_future = None
    else:
        for f in stage_files:
            html_file = (BUILD_DIR / f).with_suffix(".html")
            if html_file.exists():
                substitute_code_placeholders(html_file, outputs, code_map)

    # phase 4: assemble the served pages from staged fragments
    for target in sorted(display_targets):
        graph.update_display_page(target)
    graph.refresh_if_ready(refresh_callback)
    # If notebook outputs arrived before pandoc finished, apply them now that
    # the HTML is available.
    graph.apply_notebook_outputs(
        stage_files,
        display_targets,
        refresh_callback,
    )

    # phase 5: keep notebook execution asynchronous and refresh once complete.
    if notebook_future:
        notebook_future.add_done_callback(
            lambda future: graph.handle_notebook_future(
                future,
                notebook_executor,
                stage_files,
                display_targets,
                refresh_callback,
            )
        )

    pages = []
    for qmd in render_files:
        html_file = (DISPLAY_DIR / qmd).with_suffix(".html")
        source_path = PROJECT_ROOT / qmd
        if not source_path.exists():
            # Make it obvious which path is missing and keep the display tree
            # consistent by creating a placeholder page until pandoc produces
            # the real output.
            placeholder = (
                "<html><body><div style='color:red;font-weight:bold'>"
                f"Missing source file {source_path}"
                "</div></body></html>"
            )
            html_file.parent.mkdir(parents=True, exist_ok=True)
            html_file.write_text(placeholder)
            print(f"Cannot read title; missing source: {source_path}")
            continue
        if html_file.exists():
            sections = parse_headings(html_file)
            pages.append(
                {
                    "file": qmd,
                    "href": html_file.name,
                    "title": read_title(source_path),
                    "sections": sections,
                }
            )

    for page in pages:
        html_file = (DISPLAY_DIR / page["file"]).with_suffix(".html")
        if html_file.exists():
            add_navigation(html_file, pages, page["file"])

    return {
        "render_files": render_files,
        "tree": tree,
        "include_map": include_map,
    }


class BrowserReloader:
    def __init__(self, url: str):
        self.url = url
        self.init_browser()

    def init_browser(self):
        if webdriver is None:
            raise ImportError(
                "Browser refresh support requires the optional 'selenium'"
                " package."
            )
        try:
            self.browser = webdriver.Chrome()
        except Exception:
            self.browser = webdriver.Firefox()
        self.browser.get(self.url)

    def refresh(self):
        """Refresh the page if the browser is still open."""
        if not self.browser:
            return
        try:
            self.browser.refresh()
        except WebDriverException:
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = None

    def is_alive(self) -> bool:
        """Return True if the browser window is still open."""
        if not self.browser:
            return False
        try:
            handles = self.browser.window_handles
            if not handles:
                return False
            self.browser.execute_script("return 1")
            return True
        except (NoSuchWindowException, WebDriverException):
            return False


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, build_func, refresher):
        self.build = build_func
        self.refresher = refresher

    def handle(self, path, is_directory):
        if (
            not is_directory
            and path.endswith(".qmd")
            and "/_build/" not in path
            and "/_display/" not in path
        ):
            print(f"Change detected: {path}")
            self.build(path)
            self.refresher.refresh()

    def on_modified(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_created(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_moved(self, event):
        self.handle(event.dest_path, event.is_directory)


def _serve_forever(httpd: ThreadingHTTPServer):
    """Run the HTTP server until shutdown is called."""
    httpd.serve_forever()


def watch_and_serve(no_browser: bool = False, webtex: bool = False):
    if no_browser:
        # In headless scenarios we only need the build artifacts and can exit
        # immediately instead of launching a server loop that waits for a
        # browser connection.
        return build_all(webtex=webtex)
    port = 8000
    render_files = load_rendered_files()

    if render_files:
        start_page = Path(render_files[0]).with_suffix(".html").as_posix()
    else:
        start_page = ""
    url = f"http://localhost:{port}/{start_page}"

    print("Watching project root:")
    print(" ", PROJECT_ROOT)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DISPLAY_DIR), **kwargs)

        def translate_path(self, path):
            rel = path.lstrip("/")
            if not rel:
                rel = ""
            display_root = DISPLAY_DIR.resolve()
            build_root = BUILD_DIR.resolve()
            if rel == "_build":
                return str(build_root)
            if rel.startswith("_build/"):
                inner = rel.split("/", 1)[1]
                candidate = (BUILD_DIR / inner).resolve()
                if (
                    str(candidate).startswith(str(build_root))
                    and candidate.exists()
                ):
                    return str(candidate)
            display_candidate = (DISPLAY_DIR / rel).resolve()
            if display_candidate.exists() and str(
                display_candidate
            ).startswith(str(display_root)):
                return str(display_candidate)
            build_candidate = (BUILD_DIR / rel).resolve()
            if build_candidate.exists() and str(build_candidate).startswith(
                str(build_root)
            ):
                return str(build_candidate)
            return super().translate_path(path)

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as exc:  # pragma: no cover - depends on local environment
        print(f"Could not start server on port {port}: {exc}")
        return
    print(
        f"Serving {DISPLAY_DIR} with fallback to {BUILD_DIR} at"
        f" http://localhost:{port}"
    )
    Path(DISPLAY_DIR).mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_serve_forever, args=(httpd,), daemon=True).start()
    refresher = BrowserReloader(url)
    # Launch the initial build asynchronously so the browser opens immediately.
    initial_executor = ThreadPoolExecutor(max_workers=1)
    initial_future = initial_executor.submit(
        build_all, webtex=webtex, refresh_callback=refresher.refresh
    )
    if Observer is None:
        raise ImportError(
            "File watching requires the optional 'watchdog' package."
        )

    observer = Observer()

    def rebuild(path):
        build_all(
            webtex=webtex,
            changed_paths=[path],
            refresh_callback=refresher.refresh,
        )

    handler = ChangeHandler(rebuild, refresher)
    observer.schedule(handler, str(PROJECT_ROOT), recursive=True)
    observer.start()
    try:
        while True:
            if initial_future and initial_future.done():
                initial_future.result()
                initial_executor.shutdown(wait=False)
                initial_future = None
            if not no_browser and not refresher.is_alive():
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if initial_future:
            initial_future.result()
            initial_executor.shutdown(wait=False)
        observer.stop()
        observer.join()
        httpd.shutdown()
        httpd.server_close()
        if not no_browser and getattr(refresher, "browser", None):
            try:
                refresher.browser.quit()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build site using Pandoc")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser when using --watch",
    )
    parser.add_argument(
        "--webtex",
        action="store_true",
        help="Use Pandoc's --webtex option instead of MathJax",
    )
    args = parser.parse_args()
    watch_and_serve(no_browser=args.no_browser, webtex=args.webtex)
