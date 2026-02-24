from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import date, datetime

import textwrap
import re
import yaml
from dateutil.parser import parse as parse_due_string
from yaml.emitter import ScalarAnalysis


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

    # Render the actual due date in orange, optionally showing an original date
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
    # a glance. Upcoming deadlines within the next week are orange to match the
    # same visual emphasis used for overdue dates.
    if is_completed:
        due_color = "green"
    elif (due_date - today_date).days <= 7:
        due_color = "red"
    else:
        due_color = "orange"
    formatted = f'<font color="{due_color}">{formatted}</font>'

    if "text" in node and node["text"]:
        if node["text"].endswith("\n"):
            return node["text"] + formatted
        return node["text"] + "\n" + formatted

    return formatted


def _node_label(text, wrap_width=55):
    if text is None:
        return ""
    return _format_label(text, wrap_width)


def _normalize_graph_dates(data):
    # Normalize due dates to mm/dd/yy so the YAML is consistent across years.
    if "nodes" not in data:
        return
    default_date = datetime(date.today().year, 1, 1)
    for name in data["nodes"]:
        if (
            "due" in data["nodes"][name]
            and data["nodes"][name]["due"] is not None
        ):
            if str(data["nodes"][name]["due"]).strip():
                parsed = parse_due_string(
                    str(data["nodes"][name]["due"]).strip(),
                    default=default_date,
                )
                data["nodes"][name]["due"] = parsed.date().strftime("%m/%d/%y")
        if (
            "orig_due" in data["nodes"][name]
            and data["nodes"][name]["orig_due"] is not None
        ):
            if str(data["nodes"][name]["orig_due"]).strip():
                parsed = parse_due_string(
                    str(data["nodes"][name]["orig_due"]).strip(),
                    default=default_date,
                )
                data["nodes"][name]["orig_due"] = parsed.date().strftime(
                    "%m/%d/%y"
                )


def _append_node(
    lines, indent, node_name, data, wrap_width, order_by_date, sort_order
):
    # Add a node line with an optional sort hint so Graphviz keeps date order.
    if node_name in data["nodes"]:
        label = _node_label(
            _node_text_with_due(data["nodes"][node_name]), wrap_width
        )
    else:
        label = ""
    if label:
        if order_by_date:
            lines.append(
                f"{indent}{node_name} [label={label},"
                f" sortv={sort_order[node_name]}];"
            )
        else:
            lines.append(f"{indent}{node_name} [label={label}];")
    else:
        if order_by_date:
            lines.append(
                f"{indent}{node_name} [sortv={sort_order[node_name]}];"
            )
        else:
            lines.append(f"{indent}{node_name};")




def _style_attrs(data, style_name, attr_name):
    # Return one attribute dictionary from a style section (node/edge/etc).
    # Styles may store attrs as either a dict or a one-item list of dicts.
    if style_name not in data["styles"]:
        return {}
    if "attrs" not in data["styles"][style_name]:
        return {}
    if attr_name not in data["styles"][style_name]["attrs"]:
        return {}
    if isinstance(data["styles"][style_name]["attrs"][attr_name], list):
        if not data["styles"][style_name]["attrs"][attr_name]:
            return {}
        if not isinstance(data["styles"][style_name]["attrs"][attr_name][0], dict):
            return {}
        return data["styles"][style_name]["attrs"][attr_name][0]
    if isinstance(data["styles"][style_name]["attrs"][attr_name], dict):
        return data["styles"][style_name]["attrs"][attr_name]
    return {}

def _cluster_edge_style(data, endpoint_name):
    # Pull endpoint style attrs for cluster-origin edges.
    edge_style = ""
    if "style" in data["nodes"][endpoint_name]:
        if _style_attrs(data, data["nodes"][endpoint_name]["style"], "edge"):
            if "color" in _style_attrs(
                data, data["nodes"][endpoint_name]["style"], "edge"
            ):
                edge_style += (
                    ",color="
                    + str(
                        _style_attrs(
                            data,
                            data["nodes"][endpoint_name]["style"],
                            "edge",
                        )["color"]
                    )
                )
            if "penwidth" in _style_attrs(
                data, data["nodes"][endpoint_name]["style"], "edge"
            ):
                edge_style += (
                    ",penwidth="
                    + str(
                        _style_attrs(
                            data,
                            data["nodes"][endpoint_name]["style"],
                            "edge",
                        )["penwidth"]
                    )
                )
            if "style" in _style_attrs(
                data, data["nodes"][endpoint_name]["style"], "edge"
            ):
                edge_style += (
                    ",style="
                    + str(
                        _style_attrs(
                            data,
                            data["nodes"][endpoint_name]["style"],
                            "edge",
                        )["style"]
                    )
                )
        elif _style_attrs(data, data["nodes"][endpoint_name]["style"], "node"):
            if "color" in _style_attrs(
                data, data["nodes"][endpoint_name]["style"], "node"
            ):
                edge_style += (
                    ",color="
                    + str(
                        _style_attrs(
                            data,
                            data["nodes"][endpoint_name]["style"],
                            "node",
                        )["color"]
                    )
                )
            if "penwidth" in _style_attrs(
                data, data["nodes"][endpoint_name]["style"], "node"
            ):
                edge_style += (
                    ",penwidth="
                    + str(
                        _style_attrs(
                            data,
                            data["nodes"][endpoint_name]["style"],
                            "node",
                        )["penwidth"]
                    )
                )
    return edge_style


def yaml_to_dot(data, wrap_width=55, order_by_date=False, cluster_endpoints=True):
    lines = [
        "digraph G {",
        "    graph [",
        "        rankdir=LR,",
        "        margin=0.20,",
        "        pad=0.20,",
        "        splines=true,",
        "        concentrate=false,",
        "        center=true,",
        "        compound=true,",
        "        nodesep=0.70,",
        "        ranksep=1.00",
        "    ];",
        "    node [shape=box,width=0.5];",
    ]
    if "nodes" not in data:
        data["nodes"] = {}
    if "styles" not in data:
        data["styles"] = {}
    # Allow a YAML "default" style to set global node defaults.
    if "default" in data["styles"]:
        if _style_attrs(data, "default", "node"):
            lines.append(
                "    node ["
                + ", ".join(
                    f"{k}={v}"
                    for k, v in _style_attrs(data, "default", "node").items()
                )
                + "];"
            )
    ordered_names = None
    sort_order = None
    ordered_set = None
    if order_by_date:
        # Order nodes by due date so the graph renders boxes in calendar order.
        order_pairs = []
        for name in data["nodes"]:
            # Exclude nodes without a due date from date-ordered display.
            if (
                "due" in data["nodes"][name]
                and data["nodes"][name]["due"] is not None
            ):
                if str(data["nodes"][name]["due"]).strip():
                    due_date = parse_due_string(
                        str(data["nodes"][name]["due"]).strip()
                    ).date()
                    order_pairs.append((due_date, name))
        # Capture a stable order and use sort values so Graphviz keeps it.
        ordered_names = [
            name
            for due_date, name in sorted(
                order_pairs, key=lambda item: (item[0], item[1])
            )
        ]
        sort_order = {name: index for index, name in enumerate(ordered_names)}
        ordered_set = set(ordered_names)
    handled = set()
    endpoint_style_names = set(
        ["endpoint", "endpoints", "completedendpoint"]
    )
    endpoint_nodes = set()
    endpoint_clusters = {}
    cluster_mode = (not order_by_date) and cluster_endpoints
    if cluster_mode:
        # Build one cluster per endpoint-like node. Each cluster contains
        # non-endpoint ancestors of that endpoint, and ancestor walks stop
        # when another endpoint-like node is reached.
        for name in data["nodes"]:
            if (
                "style" in data["nodes"][name]
                and data["nodes"][name]["style"] in endpoint_style_names
            ):
                endpoint_nodes.add(name)
        for endpoint_name in endpoint_nodes:
            endpoint_clusters[endpoint_name] = set()
            parents_to_check = []
            if "parents" in data["nodes"][endpoint_name]:
                parents_to_check = list(data["nodes"][endpoint_name]["parents"])
            while parents_to_check:
                parent_name = parents_to_check.pop()
                if parent_name in endpoint_clusters[endpoint_name]:
                    continue
                if parent_name not in data["nodes"]:
                    continue
                if (
                    "style" in data["nodes"][parent_name]
                    and data["nodes"][parent_name]["style"]
                    in endpoint_style_names
                ):
                    continue
                endpoint_clusters[endpoint_name].add(parent_name)
                if "parents" in data["nodes"][parent_name]:
                    for grandparent_name in data["nodes"][parent_name]["parents"]:
                        parents_to_check.append(grandparent_name)

    # Group nodes by their declared style so they share subgraph attributes.
    style_members = {}
    for name in data["nodes"]:
        if order_by_date and name not in ordered_set:
            continue
        if cluster_mode and name in endpoint_nodes:
            # Endpoint nodes are represented by clusters in non-date mode.
            continue
        if "style" in data["nodes"][name] and data["nodes"][name]["style"]:
            style_members.setdefault(data["nodes"][name]["style"], []).append(
                name
            )

    for style_name in data["styles"]:
        if style_name not in style_members:
            continue
        if not style_members[style_name]:
            continue
        lines.append(f"    subgraph {style_name} {{")
        if _style_attrs(data, style_name, "node"):
            attr_str = ", ".join(
                f"{k}={v}" for k, v in _style_attrs(data, style_name, "node").items()
            )
            lines.append(f"        node [{attr_str}];")
        for node_name in style_members[style_name]:
            _append_node(
                lines,
                "        ",
                node_name,
                data,
                wrap_width,
                order_by_date,
                sort_order,
            )
            handled.add(node_name)
        lines.append("    };")

    if ordered_names is None:
        ordered_names = list(data["nodes"].keys())
    for name in ordered_names:
        if cluster_mode and name in endpoint_nodes:
            continue
        if name in handled:
            continue
        _append_node(
            lines,
            "    ",
            name,
            data,
            wrap_width,
            order_by_date,
            sort_order,
        )
    if cluster_mode:
        # Draw one explicit cluster per endpoint using the endpoint text for
        # the cluster label and applying endpoint style attributes to the
        # cluster box itself.
        for endpoint_name in endpoint_clusters:
            cluster_name = f"cluster_{endpoint_name}"
            lines.append(f"    subgraph {cluster_name} {{")
            if (
                "style" in data["nodes"][endpoint_name]
                and _style_attrs(data, data["nodes"][endpoint_name]["style"], "node")
            ):
                for key, value in _style_attrs(
                    data, data["nodes"][endpoint_name]["style"], "node"
                ).items():
                    lines.append(f"        {key}={value};")
            else:
                lines.append("        color=black;")
            # Cluster labels should use the same label pipeline as nodes,
            # including due-date rendering, with wider wrapping.
            if _node_text_with_due(data["nodes"][endpoint_name]) is not None:
                lines.append(
                    "        label="
                    + _format_label(
                        _node_text_with_due(data["nodes"][endpoint_name]),
                        wrap_width=wrap_width * 2,
                    )
                    + ";"
                )
            else:
                lines.append(f"        label=<{endpoint_name}>;")
            # Hidden anchor keeps edges attached to the whole cluster.
            lines.append(
                "        "
                + f"cluster_anchor_{endpoint_name}"
                + " [shape=box,width=0.01,height=0.01,fixedsize=true,label=\"\",color=white,fontcolor=white];"
            )
            for node_name in sorted(endpoint_clusters[endpoint_name]):
                lines.append(f"        {node_name};")
            # Keep the anchor near real cluster content so cluster-edge
            # routing does not drop to a dangling bottom point.
            if endpoint_clusters[endpoint_name]:
                lines.append(
                    "        "
                    + f"cluster_anchor_{endpoint_name} -> "
                    + sorted(endpoint_clusters[endpoint_name])[0]
                    + " [style=invis,weight=1];"
                )
            lines.append("    }")

    if order_by_date:
        # Arrange nodes in a grid while preserving style subgraphs.
        column_count = 5
        for index in range(0, len(ordered_names), column_count):
            lines.append(
                "    { rank=same; "
                + "; ".join(ordered_names[index : index + column_count])
                + "; }"
            )
            row_nodes = ordered_names[index : index + column_count]
            for row_index in range(len(row_nodes) - 1):
                lines.append(
                    f"    {row_nodes[row_index]} ->"
                    f" {row_nodes[row_index + 1]} [style=invis];"
                )
        for index in range(0, len(ordered_names) - column_count, column_count):
            lines.append(
                f"    {ordered_names[index]} ->"
                f" {ordered_names[index + column_count]} [style=invis];"
            )
    else:
        if cluster_mode:
            # Render each dependency edge according to endpoint/non-endpoint
            # combinations so styles and weights match the requested behavior.
            for parent_name in data["nodes"]:
                if "children" not in data["nodes"][parent_name]:
                    continue
                for child_name in data["nodes"][parent_name]["children"]:
                    if child_name not in data["nodes"]:
                        continue
                    if (
                        parent_name not in endpoint_nodes
                        and child_name not in endpoint_nodes
                    ):
                        lines.append(
                            f"    {parent_name} -> {child_name} [weight=1];"
                        )
                        continue
                    if (
                        parent_name in endpoint_nodes
                        and child_name not in endpoint_nodes
                    ):
                        edge_attrs = [
                            f"ltail=cluster_{parent_name}",
                            "tailport=e",
                            "weight=100",
                        ]
                        edge_style = _cluster_edge_style(data, parent_name)
                        if edge_style:
                            edge_attrs.append(edge_style[1:])
                        lines.append(
                            "    "
                            + f"cluster_anchor_{parent_name}"
                            + " -> "
                            + f"{child_name}"
                            + " ["
                            + ",".join(edge_attrs)
                            + "];"
                        )
                        continue
                    if (
                        parent_name not in endpoint_nodes
                        and child_name in endpoint_nodes
                    ):
                        lines.append(
                            "    "
                            + f"{parent_name}"
                            + " -> "
                            + f"cluster_anchor_{child_name}"
                            + " ["
                            + f"lhead=cluster_{child_name},headport=w,weight=1"
                            + "];"
                        )
                        continue
                    edge_attrs = [
                        f"ltail=cluster_{parent_name}",
                        f"lhead=cluster_{child_name}",
                        "tailport=e",
                        "headport=w",
                        "weight=100",
                    ]
                    edge_style = _cluster_edge_style(data, parent_name)
                    if edge_style:
                        edge_attrs.append(edge_style[1:])
                    lines.append(
                        "    "
                        + f"cluster_anchor_{parent_name}"
                        + " -> "
                        + f"cluster_anchor_{child_name}"
                        + " ["
                        + ",".join(edge_attrs)
                        + "];"
                    )
        else:
            # --no-clustering path: render all dependency edges normally.
            for name in data["nodes"]:
                if "children" in data["nodes"][name]:
                    for child in data["nodes"][name]["children"]:
                        if child in data["nodes"]:
                            lines.append(f"    {name} -> {child} [weight=1];")
    lines.append("}")
    return "\n".join(lines)


def save_graph_yaml(path, data):
    # Ensure stored dates are normalized before writing.
    _normalize_graph_dates(data)
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
    yaml_path,
    dot_path,
    update_yaml=True,
    wrap_width=55,
    order_by_date=False,
    old_data=None,
    validate_due_dates=False,
    filter_task=None,
    no_clustering=False,
):
    data = load_graph_yaml(str(yaml_path), old_data=old_data)
    _normalize_graph_dates(data)
    if validate_due_dates:
        # Enforce that no node's due date is earlier than any ancestor due date
        # so dependency timelines remain coherent.
        due_dates = {}
        for name in data["nodes"]:
            if (
                "due" in data["nodes"][name]
                and data["nodes"][name]["due"] is not None
            ):
                due_text = str(data["nodes"][name]["due"]).strip()
                if due_text:
                    due_dates[name] = parse_due_string(due_text).date()
        for name in due_dates:
            parents_to_check = [
                (parent, [parent]) for parent in data["nodes"][name]["parents"]
            ]
            seen_parents = set()
            while parents_to_check:
                parent, path = parents_to_check.pop()
                if parent in seen_parents:
                    continue
                seen_parents.add(parent)
                if parent in due_dates and due_dates[name] < due_dates[parent]:
                    path_str = " -> ".join(path)
                    raise ValueError(
                        "Refusing to render watch_graph because node "
                        f"'{name}' has due date {due_dates[name].isoformat()},"
                        " which is earlier than its ancestor "
                        f"'{parent}' due date {due_dates[parent].isoformat()}."
                        " Parent chain checked: "
                        f"{name} -> {path_str}. "
                        "Update the node's due date or adjust the parent "
                        "relationship so child due dates are not earlier than "
                        "any ancestor."
                    )
                if (
                    parent in data["nodes"]
                    and data["nodes"][parent]["parents"]
                ):
                    for grandparent in data["nodes"][parent]["parents"]:
                        parents_to_check.append(
                            (grandparent, path + [grandparent])
                        )
    data_for_dot = data
    if filter_task is not None:
        # Limit the rendered graph to incomplete ancestors of the target task.
        if "nodes" not in data or filter_task not in data["nodes"]:
            # Allow case-insensitive task lookup to align with CLI completion.
            matches = [
                name
                for name in data["nodes"]
                if name.lower() == filter_task.lower()
            ]
            if len(matches) == 1:
                filter_task = matches[0]
            elif len(matches) > 1:
                raise ValueError(
                    "Task name is ambiguous when compared case-insensitively: "
                    f"'{filter_task}' matches {matches}."
                )
            else:
                raise ValueError(
                    f"Task '{filter_task}' not found in flowchart YAML."
                )
        # Include the target task alongside its ancestors in the filtered view.
        ancestors = set([filter_task])
        parents_to_check = list(data["nodes"][filter_task]["parents"])
        while parents_to_check:
            parent = parents_to_check.pop()
            if parent in ancestors:
                continue
            ancestors.add(parent)
            if (
                parent in data["nodes"]
                and "parents" in data["nodes"][parent]
            ):
                for grandparent in data["nodes"][parent]["parents"]:
                    parents_to_check.append(grandparent)
        incomplete_ancestors = set()
        for name in ancestors:
            if name not in data["nodes"]:
                continue
            if (
                "style" in data["nodes"][name]
                and data["nodes"][name]["style"] == "completed"
            ):
                continue
            incomplete_ancestors.add(name)
        data_for_dot = {"nodes": {}, "styles": {}}
        if "styles" in data:
            data_for_dot["styles"] = data["styles"]
        for name in incomplete_ancestors:
            data_for_dot["nodes"][name] = dict(data["nodes"][name])
        for name in data_for_dot["nodes"]:
            if "children" in data_for_dot["nodes"][name]:
                data_for_dot["nodes"][name]["children"] = [
                    child
                    for child in data_for_dot["nodes"][name]["children"]
                    if child in incomplete_ancestors
                ]
            if "parents" in data_for_dot["nodes"][name]:
                data_for_dot["nodes"][name]["parents"] = [
                    parent
                    for parent in data_for_dot["nodes"][name]["parents"]
                    if parent in incomplete_ancestors
                ]
    dot_str = yaml_to_dot(
        data_for_dot,
        wrap_width=wrap_width,
        order_by_date=order_by_date,
        cluster_endpoints=(not no_clustering),
    )
    Path(dot_path).write_text(dot_str)
    if update_yaml:
        save_graph_yaml(str(yaml_path), data)
    return data
