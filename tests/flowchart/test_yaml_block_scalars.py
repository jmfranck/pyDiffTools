import textwrap
import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml


def test_multiline_strings_use_block_style(tmp_path):
    # Replaced invalid single-line block YAML with valid multi-line YAML
    yaml_text = textwrap.dedent("""
        nodes:
          Example:
            children: []
            parents: []
            text: "Line one\\n \\n\\n <font point-size=\\"12\\">\\nSecond para\
graph"
        """).strip()

    yaml_path = tmp_path / "graph.yaml"
    yaml_path.write_text(yaml_text)
    dot_path = tmp_path / "graph.dot"

    write_dot_from_yaml(yaml_path, dot_path)
    assert dot_path.exists()
    rewritten = yaml_path.read_text()

    assert "text: |-" in rewritten
    assert "\\\n" not in rewritten

    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    assert data["nodes"]["Example"]["text"].splitlines()[1] == " "
