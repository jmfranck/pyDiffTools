"""An immutable Git snapshot and a disposable plan comparison render model."""

from copy import deepcopy
from difflib import SequenceMatcher
import html
from pathlib import Path
import re
import subprocess
import tempfile

from .graph import (
    _filter_nodes_for_dot,
    _format_label,
    _normalize_graph_dates,
    _node_text_with_due,
    load_graph_yaml,
    trace_ancestors,
)


class PlanComparison:
    def __init__(self, path, revision):
        path = Path(path).resolve()
        try:
            root = Path(
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(path.parent),
                        "rev-parse",
                        "--show-toplevel",
                    ],
                    text=True,
                    stderr=subprocess.PIPE,
                ).strip()
            ).resolve()
            relative = path.relative_to(root).as_posix()
            self.commit = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(root),
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    f"{revision}^{{commit}}",
                ],
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
            listing = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-tree",
                    self.commit,
                    "--",
                    relative,
                ],
                stderr=subprocess.PIPE,
            )
            self.reference = revision
            self.data = {"nodes": {}}
            if listing:
                content = subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{self.commit}:{relative}",
                    ],
                    stderr=subprocess.PIPE,
                )
                with tempfile.NamedTemporaryFile(suffix=".yaml") as snapshot:
                    snapshot.write(content)
                    snapshot.flush()
                    self.data = load_graph_yaml(snapshot.name)
                _normalize_graph_dates(self.data)
        except Exception as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            if isinstance(detail, bytes):
                detail = detail.decode(errors="replace")
            raise ValueError(
                f"Cannot compare {path} against Git revision {revision!r}: "
                f"{detail}"
            ) from exc

    def correspondence(self, current):
        old = self.data["nodes"]
        new = current["nodes"]
        matches = {name: name for name in old.keys() & new.keys()}
        old_text = {
            k: " ".join(str(v.get("text", "")).split()) for k, v in old.items()
        }
        new_text = {
            k: " ".join(str(v.get("text", "")).split()) for k, v in new.items()
        }
        # {{{ Match unique exact content before conservative edited renames
        remaining_old = set(old) - matches.keys()
        remaining_new = set(new) - set(matches.values())
        for name in sorted(remaining_old):
            candidates = [
                k for k in remaining_new if new_text[k] == old_text[name]
            ]
            peers = [k for k in remaining_old if old_text[k] == old_text[name]]
            if len(candidates) == len(peers) == 1:
                matches[name] = candidates[0]
        remaining_old -= matches.keys()
        remaining_new -= set(matches.values())
        scores = {}
        for a in remaining_old:
            for b in remaining_new:
                scores[a, b] = SequenceMatcher(
                    None, old_text[a], new_text[b], autojunk=False
                ).ratio()
        anchors = dict(matches)
        for (a, b), score in sorted(scores.items()):
            if score < 0.9:
                continue
            alternatives = [
                v
                for (x, y), v in scores.items()
                if (x == a or y == b) and (x, y) != (a, b)
            ]
            if alternatives and score - max(alternatives) < 0.1 - 1e-9:
                continue
            agrees = True
            evidence = False
            for relation in ("parents", "children"):
                left = {
                    anchors[k]
                    for k in old[a].get(relation, [])
                    if k in anchors
                }
                right = set(new[b].get(relation, [])) & set(anchors.values())
                evidence |= bool(left or right)
                agrees &= left == right
            if agrees and evidence:
                matches[a] = b
        # }}}
        return matches

    def label(self, before, after, width):
        """Diff visible words while retaining the current label's markup."""
        deleting = bool(before) and not after
        if deleting:
            after = before
        old = _format_label(before or "", width)[1:-1]
        new = _format_label(after or "", width)[1:-1]
        old_words = re.findall(r"[^\s<>]+", re.sub(r"<[^>]*>", " ", old))
        pieces = re.findall(r"<[^>]*>|\s+|[^\s<]+", new)
        positions = [
            i
            for i, part in enumerate(pieces)
            if not part.startswith("<") and not part.isspace()
        ]
        words = [pieces[i] for i in positions]
        for op, a, b, c, d in SequenceMatcher(
            None, old_words, words, autojunk=False
        ).get_opcodes():
            for index in range(c, d):
                color = "#16803c" if op in ("insert", "replace") else "#888888"
                pos = positions[index]
                if deleting:
                    pieces[pos] = "<s>" + pieces[pos] + "</s>"
                    color = "#c62828"
                pieces[pos] = f'<font color="{color}">{pieces[pos]}</font>'
            if op in ("delete", "replace"):
                removed = " ".join(old_words[a:b])
                removed = f'<font color="#c62828"><s>{removed}</s></font> '
                if c < len(positions):
                    pieces[positions[c]] = removed + pieces[positions[c]]
                else:
                    pieces.append(removed)
        return "".join(pieces)

    def render(self, current, width, target=None, completed=False):
        matches = self.correspondence(current)
        old = self.data["nodes"]
        new = current["nodes"]
        reverse = {b: a for a, b in matches.items()}
        if target is not None:
            candidates = set(old) | set(new)
            if target not in candidates:
                candidates = [
                    k for k in candidates if k.lower() == target.lower()
                ]
                if len(candidates) != 1:
                    raise ValueError(
                        f"Task {target!r} not found or ambiguous."
                    )
                target = candidates[0]
        visible = []
        views = []
        for graph, focus in (
            (current, matches.get(target, target)),
            (self.data, reverse.get(target, target)),
        ):
            if target is not None:
                names = [focus] + trace_ancestors(graph, focus)
                view = _filter_nodes_for_dot(graph, names)
            elif completed:
                view = _filter_nodes_for_dot(graph, graph["nodes"], True)
            else:
                view = graph
            visible.append(set(view["nodes"]))
            views.append(view)
        names = visible[0] | {matches.get(k, k) for k in visible[1]}
        model = {"nodes": {}, "styles": deepcopy(current.get("styles", {}))}
        model["styles"] = {
            **deepcopy(self.data.get("styles", {})),
            **model["styles"],
        }
        self.node_states = {}
        self.edge_states = {}
        for name in sorted(names):
            previous = reverse.get(name, name if name in old else None)
            node = deepcopy(new[name] if name in new else old[name])
            before = old.get(previous, {})
            after = new.get(name, {})
            state = "same"
            if name not in new:
                state = "removed"
            elif previous is None:
                state = "added"
            body = self.label(
                before.get("text", ""), after.get("text", ""), width
            )
            if previous is not None and previous != name:
                body = (
                    f'<font color="#c62828"><s>{html.escape(previous)}</s>'
                    "</font><br/>" + body
                )
                state = "changed"
            # {{{ Explicit metadata changes, including date-only view edges
            for key in ("due", "orig_due", "style", "parents", "children"):
                left = before.get(key, "")
                right = after.get(key, "")
                if key in ("parents", "children"):
                    equal = {matches.get(k, k) for k in left} == set(right)
                else:
                    equal = left == right
                if equal:
                    if key == "due" and right:
                        dated = dict(after)
                        dated.pop("text", None)
                        body += (
                            "<br/>"
                            + _format_label(_node_text_with_due(dated), width)[
                                1:-1
                            ]
                        )
                    continue
                body += "<br/>" + self.label(
                    html.escape(f"{key}: {left or '(none)'}"),
                    html.escape(f"{key}: {right or '(none)'}"),
                    width,
                )
            # }}}
            if state == "same" and body.count("#16803c") + body.count(
                "#c62828"
            ):
                state = "changed"
            node["_comparison_label"] = body
            node["children"] = []
            node["parents"] = []
            model["nodes"][name] = node
            self.node_states[name] = state
        edges = []
        for graph, mapping in ((self.data, matches), (current, {})):
            edges.append(
                {
                    (mapping.get(a, a), mapping.get(b, b))
                    for a, node in graph["nodes"].items()
                    for b in node.get("children", [])
                }
            )
        visible_edges = {
            (mapping.get(a, a), mapping.get(b, b))
            for graph, mapping in ((views[1], matches), (views[0], {}))
            for a, node in graph["nodes"].items()
            for b in node.get("children", [])
        }
        for a, b in sorted(visible_edges):
            if a not in names or b not in names:
                continue
            model["nodes"][a]["children"].append(b)
            model["nodes"][b]["parents"].append(a)
            self.edge_states[f"{a}->{b}"] = (
                "same"
                if (a, b) in edges[0] & edges[1]
                else "added" if (a, b) in edges[1] else "removed"
            )
        return model

    def style_svg(self, root, namespace):
        for group in root.iter(f"{namespace}g"):
            kind = group.get("class")
            if kind not in ("node", "edge"):
                continue
            title = group.find(f"{namespace}title")
            states = self.node_states if kind == "node" else self.edge_states
            state = states.get(title.text if title is not None else "", "same")
            color = {"added": "#16803c", "removed": "#c62828"}.get(
                state, "#888888"
            )
            for item in group.iter():
                tag = item.tag.split("}")[-1]
                if tag in ("polygon", "path", "ellipse", "rect"):
                    item.set("stroke", color)
                    if kind == "node" and item.get("fill") != "none":
                        item.set("fill", "#f5f5f5")
                    if kind == "edge" and tag == "polygon":
                        item.set("fill", color)
                    if state == "removed":
                        item.set("stroke-dasharray", "5,3")
                elif tag == "text":
                    if state in ("added", "removed"):
                        item.set("fill", color)
                    elif item.get("fill") not in ("#16803c", "#c62828"):
                        item.set("fill", "#888888")
                    if state == "removed":
                        item.set("text-decoration", "line-through")
                    elif state == "changed" and item.text in self.node_states:
                        item.set("fill", "#16803c")
