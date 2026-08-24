#!/usr/bin/env python3
"""Minimal build script using Pandoc instead of Quarto."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading
import shutil
import queue
import yaml
from pydifftools.command_registry import register_command
from pydifftools.browser_lifecycle import (
    browser_window_is_alive,
    close_browser_window,
    forward_search_in_browser,
)
from pydifftools.forward_search import (
    FORWARD_SEARCH_HOST,
    QMDB_FORWARD_SEARCH_PORT as SHARED_QMDB_FORWARD_SEARCH_PORT,
    bind_forward_search_server,
    drain_forward_search_queue,
    serve_forward_search,
)
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver as Observer
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from jinja2 import Environment, FileSystemLoader
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
from nbconvert.preprocessors.execute import NotebookClient
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from ansi2html import Ansi2HTMLConverter

_ansi_conv = Ansi2HTMLConverter(inline=True)
PYGMENTS_CSS = Path("assets") / "pygments.css"
CODE_DISPLAY_COLLAPSED = "collapsed"
CODE_DISPLAY_ALWAYS = "always"
CODE_DISPLAY_NONE = "none"
CODE_DISPLAY_MODES = {
    CODE_DISPLAY_COLLAPSED,
    CODE_DISPLAY_ALWAYS,
    CODE_DISPLAY_NONE,
}
NB_CAPTURE_IMPORT = "from pydifftools.notebook.display import nb_capture"
NB_CAPTURE_INJECTION_VERSION = "nb_capture_auto_import_v1"
NOTEBOOK_CACHE_DIR = Path("_nbcache")
PENDING_CELL = "✗"
RUNNING_CELL = "…"
COMPLETE_CELL = "✓"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _short_time(timestamp=None):
    """Format a local timestamp compactly for the build tree."""
    if timestamp is None:
        timestamp = time.time()
    local = time.localtime(timestamp)
    hour = local.tm_hour % 12 or 12
    hundredths = int(timestamp % 1 * 100)
    return f"{hour}:{local.tm_min:02d}:{local.tm_sec:02d}.{hundredths:02d}"


def _is_noexec(code):
    for line in code.splitlines():
        if line.strip():
            return line.lstrip().startswith("%noexec")
    return False


def _notebook_groups(cells):
    """Split executable cells at ``%reset -f`` boundaries."""
    groups = []
    current = []
    for idx, (code, md5, noexec) in enumerate(cells, start=1):
        if noexec:
            continue
        if current and code.lstrip().startswith("%reset -f"):
            groups.append(current)
            current = []
        current.append((idx, code, md5))
    if current:
        groups.append(current)
    return groups


def _notebook_cache_path(src, md5s):
    cache_dir = NOTEBOOK_CACHE_DIR
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    value = (
        src
        + ":"
        + NB_CAPTURE_INJECTION_VERSION
        + ":"
        + NB_CAPTURE_IMPORT
        + ":"
        + "".join(md5s)
    ).encode()
    return cache_dir / f"{hashlib.md5(value).hexdigest()}.ipynb"


def _ansi_to_html(text: str, *, default_style: str | None = None) -> str:
    """Return HTML for text that may contain ANSI escape codes."""
    html = _ansi_conv.convert(text, full=False)
    if default_style and "span class" not in html:
        html = f'<span style="{default_style}">{html}</span>'
    return f"<pre>{html}</pre>"


def _mime_text(value) -> str:
    """Normalize a Jupyter MIME payload to text."""
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value)


def _inject_nb_capture_import(code: str) -> str:
    """Add the nb_capture import to executable code without changing source."""
    lines = code.splitlines(keepends=True)
    if any(line.strip() == NB_CAPTURE_IMPORT for line in lines):
        return code
    if not lines:
        return NB_CAPTURE_IMPORT + "\n"

    insert_at = 0
    for idx, line in enumerate(lines):
        if line.strip():
            insert_at = idx
            break
    else:
        return code + NB_CAPTURE_IMPORT + "\n"

    if lines[insert_at].lstrip().startswith("%reset -f"):
        insert_at += 1
    lines.insert(insert_at, NB_CAPTURE_IMPORT + "\n")
    return "".join(lines)


class ProgressExecutePreprocessor(ExecutePreprocessor):
    """Execute notebook cells while publishing structured progress."""

    def preprocess(self, nb, resources=None, km=None):
        NotebookClient.__init__(self, nb, km)
        self.reset_execution_trackers()
        self._check_assign_resources(resources)

        kernel_env = dict(os.environ)
        # ipykernel loads debugpy support even when no debugger was requested.
        # This kernel-only setting suppresses frozen-module validation noise.
        kernel_env["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
        callback = getattr(self, "cell_callback", None)

        with self.setup_kernel(env=kernel_env):
            assert self.kc
            info_msg = self.wait_for_reply(self.kc.kernel_info())
            assert info_msg
            self.nb.metadata["language_info"] = info_msg["content"][
                "language_info"
            ]
            for index, cell in enumerate(self.nb.cells):
                if callback:
                    callback("running", index, cell)
                self.preprocess_cell(cell, resources, index)
                if callback:
                    callback("complete", index, cell)
        self.set_widgets_metadata()

        return self.nb, self.resources


include_pattern = re.compile(
    r"\{\{\s*<\s*(include|embed)\s+([^>\s]+)\s*>\s*\}\}"
)
# Python code block pattern
code_pattern = re.compile(
    r"^\s*```(?:\{python[^}]*\}|python[^\n]*)\s*\r?\n(.*?)^\s*```",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
# Markdown image pattern
image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(
    r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}"
)


class RenderPhase(str, Enum):
    DIRTY = "dirty"
    PANDOC = "pandoc …"
    STAGING = "staging …"
    STAGED = "staged"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class RenderNode:
    path: str
    kind: str
    children: list[str]
    parents: list[str]
    revision: str | None = None
    stage_revision: str | None = None
    phase: RenderPhase = RenderPhase.DIRTY
    diagnostics: list[str] = field(default_factory=list)
    status_at: str | None = None
    notebooks: list[dict] = field(default_factory=list)
    pandoc_finished: bool = False
    required_display_targets: set[str] = field(default_factory=set)
    published_targets: set[str] = field(default_factory=set)

    @property
    def has_notebook(self):
        return bool(self.notebooks)

    @property
    def notebooks_complete(self):
        return all(
            symbol == COMPLETE_CELL
            for notebook in self.notebooks
            for symbol in notebook["states"]
        )

    @property
    def label(self):
        if self.phase == RenderPhase.DIRTY:
            return ", ".join(self.diagnostics) or "dirty"
        if self.phase == RenderPhase.FAILED:
            return self.diagnostics[-1] if self.diagnostics else "failed"
        return self.phase.value


class RenderNotebook:
    """Own the QMD dependency graph and drive it through publication."""

    def __init__(
        self,
        render_files,
        tree,
        include_map,
        code_display=CODE_DISPLAY_COLLAPSED,
        checksums=None,
    ):
        self.render_files = render_files
        self.tree = tree
        self.include_map = include_map
        self.code_display = code_display
        self.checksums = load_checksums() if checksums is None else checksums
        self.roots = {}
        self.nodes: dict[str, RenderNode] = {}
        self.notebook_outputs = {}
        self.notebook_code_map = {}
        self._last_tree = None
        self._lock = threading.RLock()
        self._build_nodes(self.checksums)

    @classmethod
    def from_project(cls, code_display=CODE_DISPLAY_COLLAPSED):
        render_files = load_rendered_files()
        tree, roots, include_map = analyze_includes(render_files)
        machine = cls(
            render_files,
            tree,
            include_map,
            code_display=code_display,
            checksums=load_checksums(),
        )
        machine.roots = roots
        return machine

    @staticmethod
    def count_code_blocks(text):
        """Count python code blocks in a Quarto document."""
        return len(code_pattern.findall(text))

    def _build_nodes(self, checksums, previous=None):
        previous = {} if previous is None else previous
        for path in [*self.render_files, *self.tree]:
            if path not in self.nodes:
                children = list(self.tree.get(path, []))
                kind = "trunk" if path in self.render_files else "branch"
                if not children and path not in self.render_files:
                    kind = "leaf"
                self.nodes[path] = RenderNode(
                    path=path,
                    kind=kind,
                    children=children,
                    parents=list(self.include_map.get(path, [])),
                )

        for path, node in self.nodes.items():
            src = PROJECT_ROOT / path
            staged_file = BUILD_DIR / path
            html_file = staged_file.with_suffix(".html")
            if src.exists():
                node.revision = self._hash_file(src)
                text = src.read_text()
                cells = []
                for code in code_pattern.findall(text):
                    cells.append(
                        (
                            code,
                            hashlib.md5(code.encode()).hexdigest(),
                            _is_noexec(code),
                        )
                    )
                html_text = html_file.read_text() if html_file.exists() else ""
                completed = completed_notebook_cells(
                    path,
                    html_text,
                    {
                        index: md5
                        for index, (_, md5, _) in enumerate(cells, start=1)
                    },
                )
                for group_idx, group in enumerate(
                    _notebook_groups(cells), start=1
                ):
                    indices = [idx for idx, _, _ in group]
                    cache_path = _notebook_cache_path(
                        path, [md5 for _, _, md5 in group]
                    )
                    if all(idx in completed for idx in indices):
                        states = [COMPLETE_CELL] * len(indices)
                        stamp = _short_time(html_file.stat().st_mtime)
                    elif cache_path.exists():
                        states = [COMPLETE_CELL] * len(indices)
                        stamp = "cached"
                    else:
                        states = [PENDING_CELL] * len(indices)
                        stamp = None
                    node.notebooks.append(
                        {
                            "index": group_idx,
                            "cell_indices": indices,
                            "states": states,
                            "stamp": stamp,
                        }
                    )
            node.status_at = _short_time(
                html_file.stat().st_mtime
                if html_file.exists()
                else src.stat().st_mtime if src.exists() else None
            )
            if (
                not src.exists()
                or not staged_file.exists()
                or not html_file.exists()
            ):
                node.diagnostics.append("missing html")
            elif checksums.get(path) != node.revision:
                node.diagnostics.append("old html")
            elif node.has_notebook and (
                "Running notebook " in html_text
                or notebook_marker_is_pending(path, html_text)
            ):
                node.diagnostics.append("unrun ipynb")
            else:
                node.phase = RenderPhase.STAGED
                node.stage_revision = node.revision

            old = previous.get(path)
            if (
                old is not None
                and old.revision == node.revision
                and old.stage_revision == node.revision
                and node.phase == RenderPhase.STAGED
                and old.phase in {RenderPhase.STAGED, RenderPhase.COMPLETE}
            ):
                node.phase = old.phase
                node.stage_revision = old.stage_revision
                node.diagnostics = list(old.diagnostics)
                node.notebooks = old.notebooks
                node.published_targets = set(old.published_targets)

        for path, node in self.nodes.items():
            targets = collect_render_targets(
                {path}, self.include_map, self.render_files
            )
            if path in self.render_files:
                targets.add(path)
            node.required_display_targets = targets
            node.published_targets.intersection_update(targets)
            if node.phase == RenderPhase.COMPLETE and not targets.issubset(
                node.published_targets
            ):
                node.phase = RenderPhase.STAGED

        for node in self.nodes.values():
            if any(
                "missing html" in self.nodes[child].diagnostics
                for child in node.children
                if child in self.nodes
            ):
                node.diagnostics.append("waiting on include build")
                if node.phase == RenderPhase.STAGED:
                    node.phase = RenderPhase.DIRTY
                    node.stage_revision = None

    def reconcile_project(self):
        """Refresh graph topology while preserving unchanged runtime state."""
        with self._lock:
            previous = self.nodes
            self.render_files = load_rendered_files()
            self.tree, self.roots, self.include_map = analyze_includes(
                self.render_files
            )
            self.checksums = load_checksums()
            self.nodes = {}
            self._build_nodes(self.checksums, previous)

    def all_paths(self):
        return list(self.nodes.keys())

    def _hash_file(self, path):
        data = path.read_bytes()
        return hashlib.md5(data).hexdigest()

    def status_contains(self, path, tag):
        if path not in self.nodes:
            return False
        node = self.nodes[path]
        return tag == node.label or tag in node.diagnostics

    def nodes_with_tag(self, tag):
        matches = []
        for path in self.nodes:
            if self.status_contains(path, tag):
                matches.append(path)
        return matches

    def invalidate_targets(self, targets):
        """Make every contributor wait for fresh publication of targets."""
        targets = set(targets)
        for node in self.nodes.values():
            if not node.required_display_targets.intersection(targets):
                continue
            node.published_targets.difference_update(targets)
            if node.phase == RenderPhase.COMPLETE:
                node.phase = RenderPhase.STAGED
                node.status_at = _short_time()

    def force_stage(self, paths):
        """Invalidate changed sources and the staged parents they feed."""
        stack = list(paths)
        forced = set()
        while stack:
            path = stack.pop()
            if path in forced or path not in self.nodes:
                continue
            forced.add(path)
            node = self.nodes[path]
            node.phase = RenderPhase.DIRTY
            node.stage_revision = None
            node.pandoc_finished = False
            node.diagnostics = ["old html"]
            node.published_targets.clear()
            stack.extend(node.parents)
        affected = set()
        for path in forced:
            affected.update(self.nodes[path].required_display_targets)
        self.invalidate_targets(affected)
        return forced

    def stage_targets(self):
        return sorted(
            path
            for path, node in self.nodes.items()
            if node.phase in {RenderPhase.DIRTY, RenderPhase.FAILED}
            and (PROJECT_ROOT / path).exists()
        )

    def update_checksums(self, staged_paths):
        for path in staged_paths:
            node = self.nodes[path]
            if node.stage_revision == node.revision:
                self.checksums[path] = node.revision

    def render_order(self):
        return build_order(self.render_files, self.tree)

    def __str__(self):
        """Return an ASCII tree of the notebook graph and status tags."""
        lines = []

        def walk(node, prefix, is_last):
            if node not in self.nodes:
                return
            branch = "└── " if is_last else "├── "
            label = node
            data = self.nodes[node]
            label += f" [{data.label}]"
            if data.status_at:
                label += " " + data.status_at
            notebooks = data.notebooks
            if notebooks:
                labels = []
                for notebook in notebooks:
                    state = "".join(notebook["states"])
                    if notebook["stamp"]:
                        state += " " + notebook["stamp"]
                    labels.append(f"n.b. #{notebook['index']}({state})")
                label += "  " + " ".join(labels)
            lines.append(prefix + branch + label)
            children = sorted(data.children)
            child_prefix = prefix + ("    " if is_last else "│   ")
            for index, child in enumerate(children):
                walk(child, child_prefix, index == len(children) - 1)

        trunks = sorted(self.render_files)
        if not trunks:
            return "<no render tree paths>"
        for index, trunk in enumerate(trunks):
            walk(trunk, "", index == len(trunks) - 1)
        return "\n".join(lines)

    @staticmethod
    def _colorize_tree(tree):
        tree = re.sub(
            r"(?<=\[)complete(?=\])",
            f"{GREEN}complete{RESET}",
            tree,
        )
        return tree.replace(
            COMPLETE_CELL, f"{GREEN}{COMPLETE_CELL}{RESET}"
        ).replace(PENDING_CELL, f"{RED}{PENDING_CELL}{RESET}")

    def print_tree_status(self):
        """Print the tree only when its status has changed."""
        with self._lock:
            tree = str(self)
            if tree == self._last_tree:
                return
            self._last_tree = tree
            if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
                tree = self._colorize_tree(tree)
            print("Build tree:", flush=True)
            for line in tree.splitlines():
                print("  " + line, flush=True)

    def set_phase(self, path, phase, diagnostic=None):
        node = self.nodes[path]
        node.phase = phase
        node.status_at = _short_time()
        node.diagnostics = [] if diagnostic is None else [diagnostic]

    def notebook_progress(
        self,
        src,
        notebook_index,
        cell_index,
        state,
        *,
        cached=False,
    ):
        """Update one cell symbol in the source's notebook status line."""
        with self._lock:
            if src not in self.nodes:
                return
            notebooks = self.nodes[src].notebooks
            if not 1 <= notebook_index <= len(notebooks):
                return
            notebook = notebooks[notebook_index - 1]
            if cell_index not in notebook["cell_indices"]:
                return
            offset = notebook["cell_indices"].index(cell_index)
            notebook["states"][offset] = {
                "running": RUNNING_CELL,
                "complete": COMPLETE_CELL,
                "cached": COMPLETE_CELL,
            }[state]
            notebook["stamp"] = "cached" if cached else _short_time()

    def pandoc_started(self, paths):
        with self._lock:
            for path in paths:
                self.set_phase(path, RenderPhase.PANDOC)

    def pandoc_failed(self, path):
        with self._lock:
            self.set_phase(path, RenderPhase.FAILED, "pandoc failed")

    def pandoc_completed(self, path):
        with self._lock:
            node = self.nodes[path]
            node.pandoc_finished = True
            self._substitute_available_outputs({path})
            if node.notebooks_complete:
                self._mark_staged(path)
            else:
                self.set_phase(path, RenderPhase.STAGING)

    def _mark_staged(self, path):
        node = self.nodes[path]
        node.stage_revision = node.revision
        self.set_phase(path, RenderPhase.STAGED)

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
            source_path = PROJECT_ROOT / target
            if source_path.exists():
                message = f"Waiting for pandoc on {target} to complete..."
            else:
                message = f"Missing source file {source_path}"
            dest_html.write_text(
                "<html><body><div style='color:red;font-weight:bold'>"
                f"{message}</div></body></html>"
            )
            return
        dest_html.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_html, dest_html)
        # Build includes using staged fragments and rewrite math assets to the
        # display tree that the web server presents.
        postprocess_html(dest_html, BUILD_DIR, DISPLAY_DIR)

    def _substitute_available_outputs(self, paths):
        for path in paths:
            html_file = (BUILD_DIR / path).with_suffix(".html")
            if html_file.exists():
                substitute_code_placeholders(
                    html_file,
                    self.notebook_outputs,
                    self.notebook_code_map,
                    code_display=self.code_display,
                )

    def update_display_targets(self, display_targets):
        """Refresh display HTML for all targets from _build fragments."""
        for target in sorted(display_targets):
            self.update_display_page(target)

    def _contributors(self, target):
        return [
            node
            for node in self.nodes.values()
            if target in node.required_display_targets
        ]

    def _target_ready(self, target):
        contributors = self._contributors(target)
        return bool(contributors) and all(
            node.stage_revision == node.revision
            and node.phase in {RenderPhase.STAGED, RenderPhase.COMPLETE}
            for node in contributors
        )

    def preview_targets(self, targets, refresh_callback=None):
        """Publish an explicitly non-final browser preview."""
        with self._lock:
            try:
                self.update_display_targets(targets)
                self.refresh_navigation(targets)
            except BaseException:
                for target in targets:
                    for node in self._contributors(target):
                        self.set_phase(
                            node.path,
                            RenderPhase.FAILED,
                            "display failed",
                        )
                self.print_tree_status()
                raise
            self.refresh_if_ready(refresh_callback)

    def publish_ready_targets(self, targets, refresh_callback=None):
        """Publish ready pages and complete their current contributors."""
        with self._lock:
            published = []
            for target in sorted(set(targets)):
                if not self._target_ready(target):
                    continue
                contributors = self._contributors(target)
                try:
                    self.update_display_page(target)
                    self.refresh_navigation({target})
                except BaseException:
                    for node in contributors:
                        self.set_phase(
                            node.path,
                            RenderPhase.FAILED,
                            "display failed",
                        )
                    self.print_tree_status()
                    raise
                for node in contributors:
                    node.published_targets.add(target)
                published.append(target)

            for node in self.nodes.values():
                if (
                    node.phase != RenderPhase.COMPLETE
                    and node.stage_revision == node.revision
                    and node.required_display_targets.issubset(
                        node.published_targets
                    )
                ):
                    self.set_phase(node.path, RenderPhase.COMPLETE)
            if published:
                self.print_tree_status()
                self.refresh_if_ready(refresh_callback)
            return published

    def record_notebook_outputs(self, outputs, code_map):
        """Merge notebook outputs that may have arrived incrementally."""
        with self._lock:
            self.notebook_outputs.update(outputs)
            self.notebook_code_map.update(code_map)

    def record_notebook_cell(self, src, idx, html, code):
        """Store one completed cell for immediate substitution."""
        if html is None or code is None:
            return
        with self._lock:
            self.notebook_outputs[(src, idx)] = html
            self.notebook_code_map[(src, idx)] = code

    def notebook_event(
        self,
        src,
        notebook_index,
        cell_index,
        state,
        *,
        html=None,
        code=None,
        cached=False,
        refresh_callback,
    ):
        """Consume a notebook worker event and drive resulting transitions."""
        with self._lock:
            self.notebook_progress(
                src,
                notebook_index,
                cell_index,
                state,
                cached=cached,
            )
            self.record_notebook_cell(src, cell_index, html, code)
            node = self.nodes.get(src)
            if node is None or not node.pandoc_finished:
                self.print_tree_status()
                return
            if state in {"complete", "cached"}:
                self._substitute_available_outputs({src})
                targets = node.required_display_targets
                if node.notebooks_complete:
                    self._mark_staged(src)
                    self.print_tree_status()
                    self.publish_ready_targets(targets, refresh_callback)
                else:
                    self.preview_targets(targets, refresh_callback)
            self.print_tree_status()

    def notebook_failed(self, paths):
        for path in paths:
            node = self.nodes[path]
            if node.has_notebook:
                self.set_phase(path, RenderPhase.FAILED, "notebook failed")

    def refresh_navigation(self, targets=None):
        """Rebuild navigation only on pages changed by this update."""
        target_set = set(self.render_files if targets is None else targets)
        pages = []
        for qmd in self.render_files:
            html_file = (DISPLAY_DIR / qmd).with_suffix(".html")
            source_path = PROJECT_ROOT / qmd
            if not source_path.exists():
                # Make it obvious which path is missing and keep the display
                # tree consistent by creating a placeholder page until pandoc
                # produces the real output.
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
            if page["file"] not in target_set:
                continue
            html_file = (DISPLAY_DIR / page["file"]).with_suffix(".html")
            if html_file.exists():
                add_navigation(html_file, pages, page["file"])

    def build(
        self,
        webtex=False,
        changed_paths=None,
        refresh_callback=None,
    ):
        """Reconcile the project and drive every affected node to display."""
        if self.code_display not in CODE_DISPLAY_MODES:
            raise ValueError(f"unknown code display mode: {self.code_display}")
        ensure_pandoc_available()
        ensure_pandoc_crossref()
        ensure_template_assets(PROJECT_ROOT)
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        DISPLAY_DIR.mkdir(parents=True, exist_ok=True)
        ensure_pygments_css(DISPLAY_DIR)
        if not webtex:
            ensure_mathjax()
            shutil.copytree(
                MATHJAX_DIR,
                DISPLAY_DIR / "mathjax",
                dirs_exist_ok=True,
            )

        self.reconcile_project()
        if yaml is not None:
            cfg = yaml.safe_load(Path("_quarto.yml").read_text())
            if "project" in cfg and "render" in cfg["project"]:
                cfg["project"]["render"] = []
            (BUILD_DIR / "_quarto.yml").write_text(yaml.safe_dump(cfg))
        else:
            (BUILD_DIR / "_quarto.yml").write_text(
                Path("_quarto.yml").read_text()
            )
        if Path("_template/obs.lua").exists():
            shutil.copy2("_template/obs.lua", BUILD_DIR / "obs.lua")

        bibliography, csl = load_bibliography_csl()
        anchors = collect_anchors(self.render_files, self.include_map)
        changed = set()
        config_changed = False
        for path in changed_paths or []:
            candidate = Path(path)
            try:
                rel = candidate.resolve().relative_to(PROJECT_ROOT)
            except ValueError:
                continue
            if rel.as_posix() == "_quarto.yml":
                config_changed = True
            elif rel.suffix == ".qmd":
                changed.add(rel.as_posix())

        if config_changed:
            self.force_stage(self.all_paths())
        elif changed:
            self.force_stage(changed)

        build_files = self.stage_targets()
        display_targets = {
            target
            for target in self.render_files
            if any(
                target in node.required_display_targets
                and target not in node.published_targets
                for node in self.nodes.values()
            )
        }
        for path in build_files:
            display_targets.update(self.nodes[path].required_display_targets)
        self.print_tree_status()

        # {{{ prepare staged QMD and notebook work
        code_blocks = mirror_and_modify(build_files, anchors, self.roots)

        def notebook_callback(
            src,
            notebook_index,
            cell_index,
            state,
            *,
            html=None,
            code=None,
            cached=False,
        ):
            self.notebook_event(
                src,
                notebook_index,
                cell_index,
                state,
                html=html,
                code=code,
                cached=cached,
                refresh_callback=refresh_callback,
            )

        notebook_executor = None
        notebook_future = None
        if code_blocks:
            notebook_executor = ThreadPoolExecutor(max_workers=1)
            notebook_future = notebook_executor.submit(
                execute_code_blocks,
                code_blocks,
                bibliography=bibliography,
                csl=csl,
                webtex=webtex,
                progress_callback=notebook_callback,
            )
        # }}}

        render_targets = [
            path for path in self.render_order() if path in build_files
        ]
        preview_targets = {
            target
            for target in display_targets
            if not self._target_ready(target)
        }
        try:
            if preview_targets:
                self.preview_targets(preview_targets, refresh_callback)
            if render_targets:
                self.pandoc_started(render_targets)
                self.print_tree_status()
                workers = max(1, min(len(render_targets), 4))
                future_to_target = {}
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for path in render_targets:
                        future = pool.submit(
                            render_file,
                            Path(path),
                            BUILD_DIR / path,
                            path not in self.render_files,
                            bibliography,
                            csl,
                            webtex,
                        )
                        future_to_target[future] = path
                    for future in as_completed(future_to_target):
                        path = future_to_target[future]
                        try:
                            future.result()
                        except BaseException:
                            self.pandoc_failed(path)
                            self.print_tree_status()
                            raise
                        self.pandoc_completed(path)
                        self.print_tree_status()
                        node = self.nodes[path]
                        if node.phase == RenderPhase.STAGED:
                            self.publish_ready_targets(
                                node.required_display_targets,
                                refresh_callback,
                            )
                        elif node.phase == RenderPhase.STAGING:
                            self.preview_targets(
                                node.required_display_targets,
                                refresh_callback,
                            )
        except BaseException:
            if notebook_executor:
                notebook_executor.shutdown(wait=True, cancel_futures=True)
            raise

        if notebook_future:
            try:
                outputs, code_map = notebook_future.result()
            except BaseException:
                self.notebook_failed(build_files)
                self.print_tree_status()
                raise
            finally:
                notebook_executor.shutdown(wait=False)
            self.record_notebook_outputs(outputs, code_map)
            for (src, idx), html in outputs.items():
                node = self.nodes.get(src)
                if node is None:
                    continue
                for notebook in node.notebooks:
                    if idx not in notebook["cell_indices"]:
                        continue
                    offset = notebook["cell_indices"].index(idx)
                    if notebook["states"][offset] != COMPLETE_CELL:
                        self.notebook_event(
                            src,
                            notebook["index"],
                            idx,
                            "complete",
                            html=html,
                            code=code_map[(src, idx)],
                            refresh_callback=refresh_callback,
                        )
                    break

        for path in build_files:
            node = self.nodes[path]
            if node.pandoc_finished and node.notebooks_complete:
                self._substitute_available_outputs({path})
                if node.phase not in {
                    RenderPhase.STAGED,
                    RenderPhase.COMPLETE,
                }:
                    self._mark_staged(path)
                    self.print_tree_status()

        self.publish_ready_targets(display_targets, refresh_callback)
        incomplete = [
            path
            for path in build_files
            if self.nodes[path].phase != RenderPhase.COMPLETE
        ]
        if incomplete:
            raise RuntimeError(
                "Build did not reach display completion for: "
                + ", ".join(incomplete)
            )
        self.update_checksums(build_files)
        save_checksums(self.checksums)
        self.print_tree_status()
        return self


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
    project = cfg.get("project", {})
    if isinstance(project, dict):
        if bib is None and "bibliography" in project:
            bib = project["bibliography"]
        if csl is None and "csl" in project:
            csl = project["csl"]
    fmt = cfg.get("format", {})
    if isinstance(fmt, dict):
        for v in fmt.values():
            if isinstance(v, dict):
                if bib is None and "bibliography" in v:
                    bib = v["bibliography"]
                if csl is None and "csl" in v:
                    csl = v["csl"]
    return bib, csl


def _add_unique_path(paths: list[Path], path: Path) -> None:
    resolved = Path(path).resolve()
    if resolved not in paths:
        paths.append(resolved)


def pandoc_resource_paths(source=None) -> list[Path]:
    """Return resource search paths for a staged source."""
    paths: list[Path] = []
    build_dir = Path(BUILD_DIR).resolve()
    display_dir = Path(DISPLAY_DIR).resolve()
    if source is not None:
        staged_src = Path(source)
        if not staged_src.is_absolute():
            staged_src = build_dir / staged_src
        staged_src = staged_src.resolve()
        _add_unique_path(paths, staged_src.parent)
        try:
            rel = staged_src.relative_to(build_dir)
        except ValueError:
            rel = Path(source)
        project_src = (PROJECT_ROOT / rel).resolve()
        display_src = (display_dir / rel).resolve()
        _add_unique_path(paths, display_src.parent)
        _add_unique_path(paths, project_src.parent)
    _add_unique_path(paths, build_dir)
    _add_unique_path(paths, display_dir)
    _add_unique_path(paths, PROJECT_ROOT)
    return paths


def pandoc_resource_path_arg(source=None) -> str:
    build_dir = Path(BUILD_DIR).resolve()
    rel_paths = []
    for path in pandoc_resource_paths(source):
        rel_paths.append(os.path.relpath(path, build_dir))
    return os.pathsep.join(rel_paths)


def render_markdown_fragment(
    text: str,
    source=None,
    bibliography=None,
    csl=None,
    webtex: bool = False,
) -> str:
    """Render a Markdown fragment to HTML using Pandoc."""
    build_dir = Path(BUILD_DIR).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "pandoc",
        "--from",
        "markdown+raw_html",
        "--to",
        "html",
        "--embed-resources",
        "--resource-path",
        pandoc_resource_path_arg(source),
    ]
    obs_filter = build_dir / "obs.lua"
    if obs_filter.exists():
        args += ["--lua-filter", os.path.relpath(obs_filter, build_dir)]
    if shutil.which("pandoc-crossref"):
        args += ["--filter", "pandoc-crossref"]
    args += ["--citeproc"]
    if webtex:
        args += ["--webtex"]
    if bibliography:
        bib_path = Path(os.path.expanduser(bibliography))
        if not bib_path.is_absolute():
            bib_path = PROJECT_ROOT / bib_path
        if not bib_path.exists():
            raise FileNotFoundError(
                f"Bibliography file {bibliography} not found"
            )
        args += ["--bibliography", os.path.relpath(bib_path, build_dir)]
    if csl:
        csl_path = Path(os.path.expanduser(csl))
        if not csl_path.is_absolute():
            csl_path = PROJECT_ROOT / csl_path
        if not csl_path.exists():
            raise FileNotFoundError(f"CSL file {csl} not found")
        args += ["--csl", os.path.relpath(csl_path, build_dir)]
    try:
        proc = subprocess.run(
            args,
            input=text,
            check=True,
            cwd=build_dir,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{e.stderr}\nwhen trying to run:{' '.join(args)}")
    return proc.stdout


def outputs_to_html(
    outputs: list[dict],
    source=None,
    bibliography=None,
    csl=None,
    webtex: bool = False,
) -> str:
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
                parts.append(_mime_text(data["text/html"]))
            elif "text/markdown" in data:
                html = render_markdown_fragment(
                    _mime_text(data["text/markdown"]),
                    source=source,
                    bibliography=bibliography,
                    csl=csl,
                    webtex=webtex,
                )
                parts.append(html)
            elif "image/png" in data:
                src = f"data:image/png;base64,{data['image/png']}"
                parts.append(f"<img src='{src}'/>")
            elif "image/jpeg" in data:
                src = f"data:image/jpeg;base64,{data['image/jpeg']}"
                parts.append(f"<img src='{src}'/>")
            elif "text/plain" in data:
                parts.append(_ansi_to_html(_mime_text(data["text/plain"])))
        elif typ == "error":
            tb = "\n".join(out.get("traceback", []))
            if not tb:
                tb = f"{out.get('ename', '')}: {out.get('evalue', '')}"
            parts.append(_ansi_to_html(tb, default_style="color:red;"))
    return "\n".join(parts)


def execute_code_blocks(
    blocks,
    bibliography=None,
    csl=None,
    webtex: bool = False,
    progress_callback=None,
):
    """Run code blocks as Jupyter notebooks with caching."""
    cache_dir = NOTEBOOK_CACHE_DIR
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    code_map = {}
    jobs = []

    for src, cells in blocks.items():
        if not cells:
            continue
        cells = [(*cell, False) if len(cell) == 2 else cell for cell in cells]
        codes = [c for c, _, _ in cells]
        for idx, (code, _, noexec) in enumerate(cells, start=1):
            if noexec:
                html = (
                    '<div style="color:#888;font-style:italic">'
                    "code skipped (%noexec)"
                    "</div>"
                )
                outputs[(src, idx)] = html
                code_map[(src, idx)] = code
                if progress_callback:
                    progress_callback(
                        src,
                        0,
                        idx,
                        "cached",
                        html=html,
                        code=code,
                        cached=True,
                    )
        groups = _notebook_groups(cells)
        for group_idx, group in enumerate(groups, start=1):
            jobs.append((src, group_idx, group, codes))

    def run_job(job):
        src, group_idx, group, codes = job
        group_indices = [idx for idx, _, _ in group]
        group_codes = [code for _, code, _ in group]
        nb_path = _notebook_cache_path(src, [md5 for _, _, md5 in group])
        group_outputs = {}
        group_code_map = {}

        def publish(state, offset, cell, *, cached=False):
            idx = group_indices[offset]
            html = None
            code = None
            if state in {"complete", "cached"}:
                html = outputs_to_html(
                    cell.get("outputs", []),
                    source=src,
                    bibliography=bibliography,
                    csl=csl,
                    webtex=webtex,
                )
                code = codes[idx - 1]
                group_outputs[(src, idx)] = html
                group_code_map[(src, idx)] = code
            if progress_callback:
                progress_callback(
                    src,
                    group_idx,
                    idx,
                    state,
                    html=html,
                    code=code,
                    cached=cached,
                )

        if nb_path.exists():
            nb = nbformat.read(nb_path, as_version=4)
            for offset, cell in enumerate(nb.cells):
                publish("cached", offset, cell, cached=True)
        else:
            nb = nbformat.v4.new_notebook()
            nb.cells = [
                nbformat.v4.new_code_cell(_inject_nb_capture_import(c))
                for c in group_codes
            ]
            ep = ProgressExecutePreprocessor(
                kernel_name="python3", timeout=10800, allow_errors=True
            )
            ep.cell_callback = publish
            try:
                ep.preprocess(
                    nb,
                    {
                        "metadata": {
                            "path": str((PROJECT_ROOT / src).parent),
                            "source": src,
                            "notebook_index": group_idx,
                        }
                    },
                )
            except Exception as error:
                tb = traceback.format_exc()
                if nb.cells:
                    nb.cells[0].outputs = [
                        nbformat.v4.new_output(
                            output_type="error",
                            ename=type(error).__name__,
                            evalue=str(error),
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
                    for offset, cell in enumerate(nb.cells):
                        publish("complete", offset, cell)
            nbformat.write(nb, nb_path)

        return group_outputs, group_code_map

    # Execute notebook chunks concurrently so long-running groups do not block.
    if jobs:
        max_workers = max(1, min(len(jobs), 4))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(run_job, job) for job in jobs]
            for future in as_completed(futures):
                group_outputs, group_code_map = future.result()
                outputs.update(group_outputs)
                code_map.update(group_code_map)

    return outputs, code_map


def analyze_includes(render_files):
    """Analyze include relationships for all render files.

    Returns a tuple ``(tree, roots, included_by)`` where:

    * ``tree`` maps each file to the files it directly includes.
    * ``roots`` maps each file to the project root directory where
      ``_quarto.yml`` lives. Includes are resolved from the including
      file's directory first, then from this project root.
    * ``included_by`` maps an included file to the files that include it.
    """

    tree: dict[str, list[str]] = {}
    included_by: dict[str, list[str]] = {}
    visited = set()

    stack = [Path(f).resolve() for f in render_files]
    root = PROJECT_ROOT
    root_dirs = {Path(f).resolve(): PROJECT_ROOT for f in render_files}

    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        try:
            key = current.relative_to(root).as_posix()
        except ValueError:
            key = current.as_posix()
        if not current.exists():
            tree.setdefault(key, [])
            continue
        includes: list[str] = []
        text = current.read_text()
        for _kind, inc in include_pattern.findall(text):
            target = (current.parent / inc).resolve()
            if not target.exists():
                target = (PROJECT_ROOT / inc).resolve()
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
            root_dirs.setdefault(target, PROJECT_ROOT)
            try:
                cur_rel = current.relative_to(root).as_posix()
            except ValueError:
                cur_rel = current.as_posix()
            included_by.setdefault(rel, []).append(cur_rel)
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
    build_dir = BUILD_DIR.resolve()
    display_dir = DISPLAY_DIR.resolve()
    for path in PROJECT_ROOT.rglob("*.qmd"):
        path = path.resolve()
        if build_dir in path.parents or display_dir in path.parents:
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
                    path.relative_to(PROJECT_ROOT).as_posix(),
                    included_by,
                    render_files,
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
QMDB_FORWARD_SEARCH_HOST = FORWARD_SEARCH_HOST
QMDB_FORWARD_SEARCH_PORT = SHARED_QMDB_FORWARD_SEARCH_PORT


class NoCacheHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve development files fresh even when rewrites share an mtime."""

    def send_head(self):
        for header in ("If-Modified-Since", "If-None-Match"):
            if header in self.headers:
                del self.headers[header]
        return super().send_head()

    def end_headers(self):
        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


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


def ensure_pygments_css(resource_root):
    """Write syntax-highlighting CSS into the display asset tree.

    We keep this as a standalone file so assembled display pages can link one
    shared stylesheet instead of relying on per-fragment inline style blocks.
    """

    css_path = resource_root / PYGMENTS_CSS
    css_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = HtmlFormatter()
    style = formatter.get_style_defs(".highlight")
    if css_path.exists():
        current = css_path.read_text()
        if current == style:
            return
    css_path.write_text(style)


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
        "always_code": (
            "Show notebook source code inline, matching the old qmdb behavior"
        ),
        "no_code": (
            "Hide notebook source code entirely and show only notebook output"
        ),
    },
)
def qmdb(
    no_browser=False,
    webtex=False,
    always_code=False,
    no_code=False,
):
    """Build and watch the current directory using the fast notebook
    builder."""

    ensure_template_assets(Path("."))
    if yaml is None or nbformat is None or Environment is None:
        # Minimal fallback when optional dependencies are unavailable.
        _write_placeholder_outputs()
        return
    code_display = resolve_code_display(
        always_code=always_code,
        no_code=no_code,
    )
    watch_and_serve(
        no_browser=no_browser,
        webtex=webtex,
        code_display=code_display,
    )


def resolve_code_display(
    always_code: bool = False,
    no_code: bool = False,
) -> str:
    """Return the notebook source-code display mode for qmdb."""
    if always_code and no_code:
        raise ValueError("--always-code and --no-code cannot be used together")
    if always_code:
        return CODE_DISPLAY_ALWAYS
    if no_code:
        return CODE_DISPLAY_NONE
    return CODE_DISPLAY_COLLAPSED


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
    code_blocks = {}
    for file in files:
        src = Path(file)
        dest = BUILD_DIR / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        text = replace_refs_text(text, anchors, dest.parent)
        root_dir = roots.get(file, PROJECT_ROOT)

        def repl(match: re.Match) -> str:
            kind, inc = match.groups()
            target_src = (src.parent / inc).resolve()
            if not target_src.exists():
                target_src = (root_dir / inc).resolve()
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
            code_blocks.setdefault(src_rel, []).append(
                (code, md5, _is_noexec(code))
            )
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

    build_dir = Path(BUILD_DIR).resolve()
    staged_src = Path(src)
    if not staged_src.is_absolute():
        staged_src = build_dir / staged_src
    output_path = Path(dest).with_suffix(".html")
    template = BODY_TEMPLATE if fragment else PANDOC_TEMPLATE
    temp = os.path.relpath(
        DISPLAY_DIR / "mathjax" / "es5" / "tex-mml-chtml.js", dest.parent
    )
    math_arg = (
        "--webtex" if webtex else (f"--mathjax={temp}?config=TeX-AMS_CHTML")
    )
    args = [
        "pandoc",
        os.path.relpath(staged_src, build_dir),
        "--from",
        "markdown+raw_html",
        "--standalone",
        "--embed-resources",
        "--resource-path",
        pandoc_resource_path_arg(staged_src),
        "--lua-filter",
        os.path.relpath(build_dir / "obs.lua", build_dir),
        "--filter",
        "pandoc-crossref",
        "--citeproc",
        math_arg,
        "--template",
        os.path.relpath(Path(template).resolve(), build_dir),
        "-o",
        os.path.relpath(output_path, build_dir),
    ]
    if bibliography:
        bib_path = Path(os.path.expanduser(bibliography))
        if not bib_path.is_absolute():
            bib_path = PROJECT_ROOT / bib_path
        if not bib_path.exists():
            raise FileNotFoundError(
                f"Bibliography file {bibliography} not found"
            )
        args += ["--bibliography", os.path.relpath(bib_path, build_dir)]
    if csl:
        csl_path = Path(os.path.expanduser(csl))
        if not csl_path.is_absolute():
            csl_path = PROJECT_ROOT / csl_path
        if not csl_path.exists():
            raise FileNotFoundError(f"CSL file {csl} not found")
        args += ["--csl", os.path.relpath(csl_path, build_dir)]
    try:
        subprocess.run(args, check=True, cwd=build_dir, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{e.stderr}\nwhen trying to run:{' '.join(args)}")


try:
    from lxml import html as lxml_html
except ImportError:
    lxml_html = None


def completed_notebook_cells(
    src: str,
    html_text: str,
    expected_hashes=None,
) -> set[int]:
    """Return unchanged cells already substituted into staged HTML."""
    completed = set()
    if not html_text or "data-script" not in html_text:
        return completed
    if lxml_html is not None:
        try:
            root = lxml_html.fromstring(html_text)
        except Exception:
            root = None
        if root is not None:
            for node in root.xpath("//div[@data-script][@data-index]"):
                if node.get("data-script") != src:
                    continue
                if node.get("data-output-state") != "complete":
                    continue
                try:
                    index = int(node.get("data-index"))
                except (TypeError, ValueError):
                    continue
                if expected_hashes is not None and node.get(
                    "data-md5"
                ) != expected_hashes.get(index):
                    continue
                completed.add(index)
            return completed
    pattern = re.compile(
        r"<div\b"
        rf"(?=[^>]*\bdata-script=['\"]{re.escape(src)}['\"])"
        r"(?=[^>]*\bdata-index=['\"]?(\d+)['\"]?)"
        r"(?=[^>]*\bdata-output-state=['\"]complete['\"])[^>]*>",
        re.IGNORECASE,
    )
    for match in pattern.finditer(html_text):
        index = int(match.group(1))
        if expected_hashes is not None:
            md5_match = re.search(
                r"\bdata-md5=['\"]([^'\"]+)['\"]", match.group(0)
            )
            if not md5_match or md5_match.group(1) != expected_hashes.get(
                index
            ):
                continue
        completed.add(index)
    return completed


def notebook_marker_is_pending(src: str, html_text: str) -> bool:
    """Return true when a rendered notebook marker has no substituted
    output."""
    if not html_text or "data-script" not in html_text or src not in html_text:
        return False
    if lxml_html is not None:
        try:
            root = lxml_html.fromstring(html_text)
        except Exception:
            root = None
        if root is not None:
            for node in root.xpath("//div[@data-script][@data-index]"):
                if node.get("data-script") != src:
                    continue
                if node.get("data-output-state") == "complete":
                    continue
                if len(node) == 0 and not "".join(node.itertext()).strip():
                    return True
            return False
    pattern = re.compile(
        r"<div\b"
        r"(?![^>]*\bdata-output-state=['\"]complete['\"])"
        rf"(?=[^>]*\bdata-script=['\"]{re.escape(src)}['\"])"
        r"(?=[^>]*\bdata-index=['\"]?\d+['\"]?)"
        r"[^>]*>\s*</div>",
        re.IGNORECASE,
    )
    return bool(pattern.search(html_text))


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

    # Always attach the shared Pygments stylesheet to the final display page.
    # Included child pages can contain highlighted blocks, but include
    # expansion only pulls body content, so we add one document-level link.
    ensure_pygments_css(resource_root)
    head = root.xpath("//head")
    if not head:
        html_nodes = root.xpath("//html")
        if html_nodes:
            new_head = lxml_html.Element("head")
            html_nodes[0].insert(0, new_head)
            head = [new_head]
    if head:
        existing_links = root.xpath(
            '//link[@rel="stylesheet" and contains(@href, "pygments.css")]'
        )
        if not existing_links:
            css_href = os.path.relpath(
                resource_root / PYGMENTS_CSS,
                html_path.parent,
            )
            link = lxml_html.fragment_fromstring(
                '<link rel="stylesheet" '
                f'href="{css_href}" id="pygments-style-link">',
                create_parent=False,
            )
            head[0].append(link)
    html_path.write_text(lxml_html.tostring(root, encoding="unicode"))


def substitute_code_placeholders(
    html_path: Path,
    outputs: dict[tuple[str, int], str],
    codes: dict[tuple[str, int], str],
    code_display: str = CODE_DISPLAY_COLLAPSED,
) -> None:
    """Replace script placeholders in ``html_path`` using executed outputs and
    embed syntax highlighted source code.
    """
    if code_display not in CODE_DISPLAY_MODES:
        raise ValueError(f"unknown code display mode: {code_display}")
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
        frags = highlighted_code_fragments(code, formatter, code_display)
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
        # Keep the data-script marker node in place so later async passes can
        # replace the temporary "Running notebook ..." block with final output.
        if missing_output:
            node.attrib.pop("data-output-state", None)
        else:
            node.set("data-output-state", "complete")
        node.text = None
        for child in list(node):
            node.remove(child)
        for frag in frags:
            node.append(frag)
        changed = True
    if changed:
        tree.write(str(html_path), encoding="utf-8", method="html")


def highlighted_code_fragments(
    code: str,
    formatter: HtmlFormatter,
    code_display: str,
) -> list:
    """Return source-code HTML fragments for the requested display mode."""
    if code_display == CODE_DISPLAY_NONE:
        return []
    code_html = highlight(code, PythonLexer(), formatter)
    frags = lxml_html.fragments_fromstring(code_html)
    if code_display == CODE_DISPLAY_ALWAYS:
        return frags

    details = lxml_html.fragment_fromstring(
        '<details class="pydifft-source">'
        "<summary>SOURCE</summary>"
        "</details>",
        create_parent=False,
    )
    for frag in frags:
        details.append(frag)
    return [details]


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
            close_browser_window(self.browser)
            self.browser = None

    def is_alive(self) -> bool:
        """Return True if the browser window is still open."""
        return browser_window_is_alive(self.browser)


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, build_func):
        self.build = build_func

    def handle(self, path, is_directory):
        source_path = Path(path)
        is_source_file = source_path.suffix == ".qmd"
        is_project_config = source_path.name == "_quarto.yml"
        if (
            not is_directory
            and (is_source_file or is_project_config)
            and "/_build/" not in path
            and "/_display/" not in path
        ):
            print(f"Change detected: {path}")
            self.build(path)

    def on_modified(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_created(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_moved(self, event):
        self.handle(event.dest_path, event.is_directory)

    def on_deleted(self, event):
        self.handle(event.src_path, event.is_directory)


def _serve_forever(httpd: ThreadingHTTPServer):
    """Run the HTTP server until shutdown is called."""
    httpd.serve_forever()


def watch_and_serve(
    no_browser: bool = False,
    webtex: bool = False,
    code_display: str = CODE_DISPLAY_COLLAPSED,
):
    machine = RenderNotebook.from_project(code_display=code_display)
    if no_browser:
        # In headless scenarios we only need the build artifacts and can exit
        # immediately instead of launching a server loop that waits for a
        # browser connection.
        return machine.build(webtex=webtex)
    port = 8000
    render_files = load_rendered_files()

    if render_files:
        start_page = Path(render_files[0]).with_suffix(".html").as_posix()
    else:
        start_page = ""
    url = f"http://localhost:{port}/{start_page}"

    print("Watching project root:")
    print(" ", PROJECT_ROOT)

    class Handler(NoCacheHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DISPLAY_DIR), **kwargs)

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as exc:  # pragma: no cover - depends on local environment
        print(f"Could not start server on port {port}: {exc}")
        return
    try:
        forward_search_server = bind_forward_search_server(
            (QMDB_FORWARD_SEARCH_HOST, QMDB_FORWARD_SEARCH_PORT), "qmdb"
        )
    except Exception:
        httpd.server_close()
        raise
    forward_search_stop = threading.Event()
    forward_search_queue = queue.Queue()
    forward_search_thread = threading.Thread(
        target=serve_forward_search,
        args=(
            forward_search_server,
            forward_search_stop,
            forward_search_queue,
        ),
        daemon=True,
    )
    refresher = None
    initial_executor = None
    initial_future = None
    observer = None
    observer_started = False
    forward_search_thread_started = False

    try:
        # The endpoint is live before BrowserReloader constructs Chrome.
        forward_search_thread.start()
        forward_search_thread_started = True
        print(f"Serving {DISPLAY_DIR} at http://localhost:{port}")
        Path(DISPLAY_DIR).mkdir(parents=True, exist_ok=True)
        threading.Thread(
            target=_serve_forever, args=(httpd,), daemon=True
        ).start()
        refresher = BrowserReloader(url)
        build_lock = threading.Lock()

        def serialized_build(**kwargs):
            with build_lock:
                return machine.build(**kwargs)

        # Launch the initial build asynchronously so Chrome opens immediately.
        initial_executor = ThreadPoolExecutor(max_workers=1)
        initial_future = initial_executor.submit(
            serialized_build,
            webtex=webtex,
            refresh_callback=refresher.refresh,
        )
        if Observer is None:
            raise ImportError(
                "File watching requires the optional 'watchdog' package."
            )

        observer = Observer()

        def rebuild(path):
            serialized_build(
                webtex=webtex,
                changed_paths=[path],
                refresh_callback=refresher.refresh,
            )

        handler = ChangeHandler(rebuild)
        observer.schedule(handler, str(PROJECT_ROOT), recursive=True)
        observer.start()
        observer_started = True
        while True:
            if not forward_search_thread.is_alive():
                raise RuntimeError(
                    "The qmdb forward-search listener stopped unexpectedly; "
                    "closing the preview instead of leaving an "
                    "undiscoverable session."
                )
            if initial_future and initial_future.done():
                initial_future.result()
                initial_executor.shutdown(wait=False)
                initial_future = None
                initial_executor = None
            for search_text in drain_forward_search_queue(
                forward_search_queue
            ):
                # Reuse cpb forward-search behavior for qmdb browser windows.
                try:
                    forward_search_in_browser(
                        refresher.browser, search_text
                    )
                except WebDriverException:
                    close_browser_window(refresher.browser)
                    refresher.browser = None
            if not no_browser and not refresher.is_alive():
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        forward_search_stop.set()
        forward_search_server.close()
        if observer_started:
            observer.stop()
            observer.join()
        if initial_executor is not None:
            initial_executor.shutdown(wait=True)
        httpd.shutdown()
        httpd.server_close()
        if refresher is not None and getattr(refresher, "browser", None):
            close_browser_window(refresher.browser)
        if forward_search_thread_started:
            forward_search_thread.join()


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
    code_group = parser.add_mutually_exclusive_group()
    code_group.add_argument(
        "--always-code",
        action="store_true",
        help="Show notebook source code inline",
    )
    code_group.add_argument(
        "--no-code",
        action="store_true",
        help="Hide notebook source code and show only notebook output",
    )
    args = parser.parse_args()
    watch_and_serve(
        no_browser=args.no_browser,
        webtex=args.webtex,
        code_display=resolve_code_display(
            always_code=args.always_code,
            no_code=args.no_code,
        ),
    )
