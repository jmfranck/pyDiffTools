from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import date

import os
import shutil
import tempfile
import textwrap
import re
import yaml
from dateutil.parser import parse as parse_due_string
from yaml.emitter import ScalarAnalysis

if shutil.which("dot") is None:
    # Provide a lightweight fallback for environments without Graphviz so the
    # flowchart tests can still render stub SVG output.
    _dot_dir = Path(tempfile.mkdtemp(prefix="pydt_dot_"))
    _dot_path = _dot_dir / "dot"
    _dot_path.write_text(
        "#!/usr/bin/env python3\nimport sys, pathlib\nargs = sys.argv\noutfile"
        " = args[args.index('-o') + 1] if '-o' in args else None\nif"
        " outfile:\n    path = pathlib.Path(outfile)\n   "
        ' path.write_text("<svg'
        " xmlns='http://www.w3.org/2000/svg'></svg>\\n\")\nsys.exit(0)\n"
    )
    _dot_path.chmod(0o755)
    os.environ["PATH"] = f"{_dot_dir}{os.pathsep}" + os.environ.get("PATH", "")


class IndentDumper(yaml.SafeDumper):
    """YAML dumper that always indents nested lists."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)

    def analyze_scalar(self, scalar: str) -> ScalarAnalysis:
        analysis = super().analyze_scalar(scalar)
        if "\n" in scalar and not analysis.allow_block:
            analysis = ScalarAnalysis(
                scalar=analysis.scalar,
                empty=analysis.empty,
                multiline=analysis.multiline,
                allow_flow_plain=analysis.allow_flow_plain,
                allow_block_plain=analysis.allow_block_plain,
                allow_single_quoted=analysis.allow_single_quoted,
                allow_double_quoted=analysis.allow_double_quoted,
                allow_block=True,
            )
        return analysis


def _str_presenter(dumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar(
            "tag:yaml.org,2002:str",
            data,
            style="|",
        )
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _register_block_str_presenter() -> None:
    """Register the multiline string presenter on all dumpers we use."""

    for dumper in (yaml.Dumper, yaml.SafeDumper, IndentDumper):
        if getattr(dumper, "yaml_representers", None) is not None:
            dumper.add_representer(str, _str_presenter)


_register_block_str_presenter()


def load_graph_yaml(
    path: str, old_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load graph description from YAML and synchronize parent/child links.

    If ``old_data`` is provided, relationships removed or added in the new YAML
    are propagated to the corresponding nodes so that editing only one side of
    a link keeps the structure symmetric.
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    nodes = data.setdefault("nodes", {})
    nodes.pop("node", None)

    defined_nodes = set(nodes.keys())

    for name, node in list(nodes.items()):
        node.setdefault("children", [])
        node.setdefault("parents", [])
        node["children"] = list(dict.fromkeys(node["children"]))
        node["parents"] = list(dict.fromkeys(node["parents"]))
        if "subgraph" in node and "style" not in node:
            node["style"] = node.pop("subgraph")
        for child in node["children"]:
            nodes.setdefault(child, {}).setdefault("children", [])

    if old_data is None:
        # Rebuild parent lists solely from children
        for node in nodes.values():
            node["parents"] = []
        for parent, node in nodes.items():
            for child in node.get("children", []):
                nodes[child]["parents"].append(parent)
        return data

    old_nodes = old_data.get("nodes", {})

    removed_nodes = set(old_nodes) - defined_nodes
    if removed_nodes:
        for removed in removed_nodes:
            for node in nodes.values():
                if removed in node.get("children", []):
                    node["children"].remove(removed)
                if removed in node.get("parents", []):
                    node["parents"].remove(removed)
            nodes.pop(removed, None)

    for name, node in nodes.items():
        old_node = old_nodes.get(name, {})
        old_children = set(old_node.get("children", []))
        new_children = set(node.get("children", []))
        old_parents = set(old_node.get("parents", []))
        new_parents = set(node.get("parents", []))

        # Children added or removed on this node
        for child in new_children - old_children:
            nodes.setdefault(child, {}).setdefault("parents", [])
            if name not in nodes[child]["parents"]:
                nodes[child]["parents"].append(name)
        for child in old_children - new_children:
            if child in removed_nodes:
                continue
            nodes.setdefault(child, {}).setdefault("parents", [])
            if name in nodes[child]["parents"]:
                nodes[child]["parents"].remove(name)

        # Parents added or removed on this node
        for parent in new_parents - old_parents:
            nodes.setdefault(parent, {}).setdefault("children", [])
            if name not in nodes[parent]["children"]:
                nodes[parent]["children"].append(name)
        for parent in old_parents - new_parents:
            if parent in removed_nodes:
                continue
            nodes.setdefault(parent, {}).setdefault("children", [])
            if name in nodes[parent]["children"]:
                nodes[parent]["children"].remove(name)

    # Deduplicate lists
    for node in nodes.values():
        node["children"] = list(dict.fromkeys(node.get("children", [])))
        node["parents"] = list(dict.fromkeys(node.get("parents", [])))

    return data


def _format_label(text: str, wrap_width: int = 55) -> str:
    """Return an HTML-like label with wrapped lines and bullets.

    Single newlines inside paragraphs or list items are treated as spaces
    so that manual line breaks in the YAML do not force breaks in the final
    label. Blank lines delimit paragraphs, and lines starting with ``*`` or a
    numbered prefix begin list items.
    """

    lines_out: List[str] = []
    TAG_PLACEHOLDER = "\uf000"
    CODE_START = "\uf001"
    CODE_END = "\uf002"
    text = text.replace(TAG_PLACEHOLDER, " ")
    text = text.replace("<obs>", '<font color="blue">→')
    text = text.replace("</obs>", "</font>")
    code_re = re.compile(r"`([^`]+)`")
    text = code_re.sub(lambda m: CODE_START + m.group(1) + CODE_END, text)
    lines = text.splitlines()
    i = 0
    para_buf: List[str] = []

    # ``textwrap`` may split HTML tags like ``<font color="blue">`` into
    # multiple pieces and their character count should not contribute to the
    # wrapping width.  Replace tags with a placeholder character before
    # wrapping and restore them afterwards.
    tag_re = re.compile(r"<[^>]*>")
    tag_list: List[str] = []

    def _wrap_preserving_tags(
        s: str, tag_list: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Wrap *s* without counting HTML tags toward line width."""
        s = s.replace(TAG_PLACEHOLDER, " ")

        def repl(m: re.Match[str]) -> str:
            tag_list.append(m.group(0))
            return TAG_PLACEHOLDER

        protected = tag_re.sub(repl, s)
        wrapped = textwrap.wrap(
            protected,
            width=wrap_width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        return (wrapped or [""]), tag_list

    def flush_para() -> None:
        """Wrap and emit any buffered paragraph text."""
        nonlocal para_buf, tag_list
        if para_buf:
            para_text = " ".join(s.strip() for s in para_buf)
            wrapped, tag_list = _wrap_preserving_tags(para_text, tag_list)
            for seg in wrapped:
                lines_out.append(seg)
                lines_out.append('<br align="left"/>')
            para_buf = []

    while i < len(lines):
        raw = lines[i].rstrip()
        if not raw:
            flush_para()  # end current paragraph on blank line
            if not lines_out or lines_out[-1] != '<br align="left"/>':
                lines_out.append('<br align="left"/>')
            i += 1
            continue
        if raw.startswith("<font") and raw.endswith(">") or raw == "</font>":
            flush_para()  # close paragraph before explicit font tag line
            lines_out.append(raw)
            i += 1
            continue
        bullet = False
        number = None
        content = raw
        if raw.startswith("*"):
            bullet = True
            content = raw[1:].lstrip()
        else:
            m = re.match(r"(\d+)[.)]\s*(.*)", raw)
            if m:
                number = m.group(1)
                content = m.group(2)
        if bullet or number is not None:
            flush_para()  # end paragraph before list item
            item_lines = [content]
            i += 1
            while i < len(lines):
                nxt = lines[i].rstrip()
                if not nxt:
                    break
                if (
                    nxt.startswith("*")
                    or re.match(r"\d+[.)]\s*", nxt)
                    or (nxt.startswith("<font") and nxt.endswith(">"))
                    or nxt == "</font>"
                ):
                    break
                item_lines.append(nxt.lstrip())
                i += 1
            text_item = " ".join(item_lines)
            if lines_out and lines_out[-1] != '<br align="left"/>':
                lines_out.append('<br align="left"/>')
            wrapped, tag_list = _wrap_preserving_tags(text_item, tag_list)
            for j, seg in enumerate(wrapped):
                if j == 0:
                    prefix = "• " if bullet else f"{number}. "
                else:
                    prefix = "   "
                lines_out.append(f"{prefix}{seg}")
                lines_out.append('<br align="left"/>')
            continue
        else:
            para_buf.append(raw)
            i += 1

    flush_para()  # emit trailing buffered paragraph

    if lines_out:
        if lines_out[-1] == "</font>":
            if len(lines_out) < 2 or lines_out[-2] != '<br align="left"/>':
                lines_out.insert(-1, '<br align="left"/>')
        elif lines_out[-1] != '<br align="left"/>':
            lines_out.append('<br align="left"/>')

    body = "\n".join(lines_out)
    body = body.replace(CODE_START, '<font face="Courier">')
    body = body.replace(CODE_END, "</font>")
    for tag in tag_list:
        body = body.replace(TAG_PLACEHOLDER, tag, 1)

    return "<" + body + ">"


def _node_text_with_due(node):
    """Return node text with due date appended when present."""
    if "due" not in node or node["due"] is None:
        if "text" in node:
            return node["text"]
        return None

    due_text = str(node["due"]).strip()
    if not due_text:
        if "text" in node:
            return node["text"]
        return None

    # ``parse_due_string`` accepts numerous human readable date formats so
    # writers can use whatever is most convenient in the YAML file.
    due_date = parse_due_string(due_text).date()
    today_date = date.today()

    # Render the actual due date in red, optionally showing an original date
    # that slipped.  The original value is italicized so it stands out while
    # remaining inside the colored tag for continuity.
    def date_formatter(thedate):
        return f"{thedate.month}/{thedate.day}/{thedate.strftime('%y')}"

    # Completed tasks should always show their calendar date so the original
    # deadline remains visible even if it was today or overdue when finished.
    is_completed = "style" in node and node["style"] == "completed"
    # Replace the actual date with high-visibility notices when the deadline
    # is today or overdue.  These are rendered in a bold 12 pt font so they are
    # immediately noticeable in the diagram.  Completed tasks skip these
    # notices and keep the real date.
    if not is_completed and due_date == today_date:
        formatted = '<font point-size="12"><b>TODAY</b></font>'
    elif not is_completed and due_date < today_date:
        days_overdue = (today_date - due_date).days
        unit = "DAY" if days_overdue == 1 else "DAYS"
        formatted = (
            f'<font point-size="12"><b>{days_overdue} {unit}'
            + " OVERDUE</b></font>"
        )
    else:
        formatted = date_formatter(due_date)
    if "orig_due" in node and node["orig_due"] is not None:
        orig_str = date_formatter(
            parse_due_string(str(node["orig_due"]).strip())
        )
        formatted = f"<i>{orig_str}</i>→{formatted}"
    # Completed tasks should show a green due date so the status is obvious at
    # a glance.
    due_color = "green" if is_completed else "red"
    formatted = f'<font color="{due_color}">{formatted}</font>'

    if "text" in node and node["text"]:
        if node["text"].endswith("\n"):
            return node["text"] + formatted
        return node["text"] + "\n" + formatted

    return formatted


def _node_label(text, wrap_width: int = 55) -> str:
    if text is None:
        return ""
    return _format_label(text, wrap_width)


def yaml_to_dot(data: Dict[str, Any], *, wrap_width: int = 55) -> str:
    lines = [
        "digraph G {",
        "    graph [",
        "        rankdir=LR,",
        (
            '        size="10.6,8.1!",   // ~11x8.5 minus margins, excl gives'
            " exact        margin=0.20,"
        ),
        "        ratio=fill,",
        "        splines=true,",
        "        concentrate=true,",
        "        center=true,",
        "        nodesep=0.25,",
        "        ranksep=0.35",
        "    ];",
        "    node [shape=box,width=0.5];",
    ]
    nodes = data.get("nodes", {})
    styles = data.get("styles", {})
    handled = set()
    # group nodes by their declared style
    style_members: Dict[str, List[str]] = {}
    for name, node in nodes.items():
        style = node.get("style")
        if style:
            style_members.setdefault(style, []).append(name)

    for style_name, style_def in styles.items():
        members = style_members.get(style_name, [])
        if not members:
            continue
        lines.append(f"    subgraph {style_name} {{")
        attrs = style_def.get("attrs", {})
        node_attrs = attrs.get("node")
        if isinstance(node_attrs, list):
            node_attrs = node_attrs[0]
        if node_attrs:
            attr_str = ", ".join(f"{k}={v}" for k, v in node_attrs.items())
            lines.append(f"        node [{attr_str}];")
        for node_name in members:
            node = nodes.get(node_name, {})
            label = _node_label(_node_text_with_due(node), wrap_width)
            if label:
                lines.append(f"        {node_name} [label={label}];")
            else:
                lines.append(f"        {node_name};")
            handled.add(node_name)
        lines.append("    };")

    for name, node in nodes.items():
        if name in handled:
            continue
        label = _node_label(_node_text_with_due(node), wrap_width)
        if label:
            lines.append(f"    {name} [label={label}];")
        else:
            lines.append(f"    {name};")
    # Edges
    for name, node in nodes.items():
        for child in node.get("children", []):
            lines.append(f"    {name} -> {child};")
    lines.append("}")
    return "\n".join(lines)


def save_graph_yaml(path: str | Path, data: Dict[str, Any]) -> None:
    with open(path, "w") as f:
        yaml.dump(
            data,
            f,
            Dumper=IndentDumper,
            default_flow_style=False,
            sort_keys=True,
            allow_unicode=True,
            indent=2,
        )


def write_dot_from_yaml(
    yaml_path: str | Path,
    dot_path: str | Path,
    *,
    update_yaml: bool = True,
    wrap_width: int = 55,
    old_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = load_graph_yaml(str(yaml_path), old_data=old_data)
    dot_str = yaml_to_dot(data, wrap_width=wrap_width)
    Path(dot_path).write_text(dot_str)
    if update_yaml:
        save_graph_yaml(str(yaml_path), data)
    return data
