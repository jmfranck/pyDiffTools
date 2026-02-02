import re
import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml


def test_observation_tags_rendered(tmp_path):
    data = {"nodes": {"A": {"text": "Before <obs>Observation</obs> after"}}}
    yaml_path = tmp_path / "obs.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    dot_path = tmp_path / "obs.dot"
    write_dot_from_yaml(yaml_path, dot_path, wrap_width=100)
    text = dot_path.read_text()

    m = re.search(r"A \[label=<(.*)>\s*];", text, re.S)
    assert m, "label not found"
    label = m.group(1)

    assert '<font color="blue">→Observation</font>' in label
    assert "<obs>" not in label
    assert "</obs>" not in label
    assert '→Observation</font> after\n<br align="left"/>' in label
