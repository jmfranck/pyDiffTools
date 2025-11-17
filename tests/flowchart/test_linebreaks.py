import re
import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml

def test_single_linebreak_ignored(tmp_path):
    data = {
        'nodes': {
            'A': {
                'text': 'First line\nsecond line'
            }
        }
    }
    yaml_path = tmp_path / 'g.yaml'
    with open(yaml_path, 'w') as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    dot_path = tmp_path / 'g.dot'
    write_dot_from_yaml(yaml_path, dot_path, wrap_width=100)
    text = dot_path.read_text()
    m = re.search(r'A \[label=<(.*?)>\];', text, re.S)
    assert m, 'label not found'
    label = m.group(1)
    assert 'First line second line' in label
    assert 'First line\nsecond line' not in label
