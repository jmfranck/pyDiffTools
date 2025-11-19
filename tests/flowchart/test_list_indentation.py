import sys, pathlib
import re
import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml


def _extract_segments(label: str):
    parts = re.findall(r'([^<]*)<br align="left"/>', label)
    return [p.rstrip('\n').split('\n')[-1] for p in parts]


def test_bullet_overflow_indent(tmp_path):
    data = {
        'nodes': {
            'A': {
                'text': '* ' + 'word ' * 20,
            }
        }
    }
    yaml_path = tmp_path / 'g.yaml'
    with open(yaml_path, 'w') as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    dot_path = tmp_path / 'g.dot'
    write_dot_from_yaml(yaml_path, dot_path, wrap_width=20)
    text = dot_path.read_text()
    m = re.search(r'A \[label=<(.*?)>\];', text, re.S)
    assert m, 'label not found'
    label = m.group(1)
    segments = _extract_segments(label)
    assert segments[0].startswith('• ')
    assert segments[1].startswith('  ')


def test_numbered_overflow_indent(tmp_path):
    data = {
        'nodes': {
            'A': {
                'text': '1. ' + 'word ' * 20,
            }
        }
    }
    yaml_path = tmp_path / 'g.yaml'
    with open(yaml_path, 'w') as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    dot_path = tmp_path / 'g.dot'
    write_dot_from_yaml(yaml_path, dot_path, wrap_width=20)
    text = dot_path.read_text()
    m = re.search(r'A \[label=<(.*?)>\];', text, re.S)
    assert m, 'label not found'
    label = m.group(1)
    segments = _extract_segments(label)
    assert segments[0].startswith('1. ')
    assert segments[1].startswith('  ')
