import re
import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml


def test_inline_code_wrapped_with_courier_font(tmp_path):
    data = {
        "nodes": {
            "A": {
                "text": "Before `inline code` and `second bit` after",
            }
        }
    }
    yaml_path = tmp_path / "inline.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    dot_path = tmp_path / "inline.dot"
    write_dot_from_yaml(yaml_path, dot_path, wrap_width=100)
    text = dot_path.read_text()

    m = re.search(r"A \[label=<(.*)>\s*];", text, re.S)
    assert m, "label not found"
    label = m.group(1)

    assert '<font face="Courier">inline code</font>' in label
    assert '<font face="Courier">second bit</font>' in label
    assert "`" not in label
