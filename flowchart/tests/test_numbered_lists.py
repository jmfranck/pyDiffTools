import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import re
import yaml
from dot_to_yaml import dot_to_yaml
from graph import write_dot_from_yaml

def test_numbered_lines(tmp_path):
    tmp_yaml = tmp_path / 'out.yaml'
    dot_to_yaml('magnet_setup.dot', tmp_yaml)
    data = yaml.safe_load(tmp_yaml.read_text())
    lines = data['nodes']['Disconnect']['text'].splitlines()
    assert lines[3].startswith('1.')
    assert lines[4].startswith('2.')
    assert lines[5].startswith('3.')
    generated_dot = tmp_path / 'from_yaml.dot'
    write_dot_from_yaml(tmp_yaml, generated_dot)
    text = generated_dot.read_text()
    m = re.search(r'Disconnect \[label=<(.*?)>\];', text, re.S)
    assert m, 'label not found'
    label = m.group(1)
    assert re.search(r'<br align="left"/>\n\s*2\. Add notes', label)
    assert label.strip().endswith('<br align="left"/>' + '\n</font>')
