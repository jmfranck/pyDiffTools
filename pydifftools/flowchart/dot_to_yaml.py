import sys
import re
import yaml
import pydot

from .graph import IndentDumper


def _label_to_text(label: str) -> str:
    if label is None:
        return None
    stripped = label.strip()
    if stripped.startswith('<') and stripped.endswith('>'):
        stripped = stripped[1:-1]
    stripped = stripped.replace('<br align="left"/>', '\n')
    stripped = stripped.replace('<br/>', '\n')
    lines = [l.strip() for l in stripped.splitlines()]
    out_lines = []
    current: list[str] = []

    def flush():
        nonlocal current
        if current:
            out_lines.append(' '.join(current))
            current = []

    for s in lines:
        if not s:
            continue
        if s.startswith('<font'):
            flush()
            if out_lines and out_lines[-1] != '':
                out_lines.append('')
            out_lines.append(s)
        elif s.startswith('</font'):
            flush()
            out_lines.append(s)
        elif s.startswith('•'):
            flush()
            current = ['* ' + s[1:].lstrip()]
        elif re.match(r'\d+[.)]\s', s):
            flush()
            current = [s]
        else:
            if current:
                current.append(s)
            else:
                current = [s]
    flush()
    return '\n'.join(out_lines)


def dot_to_yaml(dot_path, yaml_path):
    graphs = pydot.graph_from_dot_file(dot_path)
    if not graphs:
        raise ValueError("No graph found in dot file")
    graph = graphs[0]
    nodes = {}
    for node in graph.get_nodes():
        name = node.get_name().strip('"')
        if name in ('graph', 'node', 'edge'):
            continue
        label = node.get('label')
        if label is not None:
            label = label.strip('"')
            label = _label_to_text(label)
        nodes[name] = {
            'text': label,
            'children': [],
            'parents': [],
        }
    styles = {}
    for sub in graph.get_subgraphs():
        sub_name = sub.get_name().strip('"')
        attrs = {}
        if sub.get_node_defaults():
            attrs['node'] = sub.get_node_defaults()
        styles[sub_name] = {'attrs': attrs}
        for n in sub.get_nodes():
            nname = n.get_name().strip('"')
            if nname == 'node':
                continue
            if nname not in nodes:
                label = n.get('label')
                if label is not None:
                    label = label.strip('"')
                    label = _label_to_text(label)
                nodes[nname] = {'text': label, 'children': [], 'parents': []}
            nodes[nname]['style'] = sub_name
    for edge in graph.get_edges():
        src = edge.get_source().strip('"')
        dst = edge.get_destination().strip('"')
        nodes.setdefault(src, {'text': None, 'children': [], 'parents': []})
        nodes.setdefault(dst, {'text': None, 'children': [], 'parents': []})
        nodes[src]['children'].append(dst)
        nodes[dst]['parents'].append(src)
    data = {'styles': styles, 'nodes': nodes}
    with open(yaml_path, 'w') as f:
        yaml.dump(
            data,
            f,
            Dumper=IndentDumper,
            default_flow_style=False,
            sort_keys=True,
            allow_unicode=True,
            indent=2,
        )


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: dot_to_yaml.py <input.dot> <output.yaml>')
        sys.exit(1)
    dot_to_yaml(sys.argv[1], sys.argv[2])
