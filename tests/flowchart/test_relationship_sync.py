import yaml

from pydifftools.flowchart.graph import write_dot_from_yaml


def test_relationship_removal_updates_yaml(tmp_path):
    yaml_path = tmp_path / 'graph.yaml'
    yaml_path.write_text('''\
nodes:
  BringInNewDesk:
    children: []
    parents: []
  SetUpDedicatedComputer:
    children: []
    parents:
    - BringInNewDesk
''')
    dot_path = tmp_path / 'graph.dot'
    write_dot_from_yaml(yaml_path, dot_path)
    data = yaml.safe_load(yaml_path.read_text())
    assert data['nodes']['SetUpDedicatedComputer']['parents'] == []


def test_parent_removal_updates_yaml(tmp_path):
    yaml_path = tmp_path / 'graph.yaml'
    yaml_path.write_text('''\
nodes:
  EstimateRatio:
    children:
    - CheckMagnet
    parents: []
  CheckMagnet:
    children: []
    parents:
    - EstimateRatio
''')
    dot_path = tmp_path / 'graph.dot'
    data = write_dot_from_yaml(yaml_path, dot_path)
    data_yaml = yaml.safe_load(yaml_path.read_text())
    # simulate user removing parent link only
    data_yaml['nodes']['CheckMagnet']['parents'] = []
    yaml_path.write_text(yaml.safe_dump(data_yaml))
    write_dot_from_yaml(yaml_path, dot_path, old_data=data)
    updated = yaml.safe_load(yaml_path.read_text())
    assert 'CheckMagnet' not in updated['nodes']['EstimateRatio']['children']


def test_node_removal_cleans_references(tmp_path):
    yaml_path = tmp_path / 'graph.yaml'
    yaml_path.write_text('''\
nodes:
  A:
    children:
    - B
    parents: []
  B:
    children: []
    parents:
    - A
''')
    dot_path = tmp_path / 'graph.dot'
    data = write_dot_from_yaml(yaml_path, dot_path)
    data_yaml = yaml.safe_load(yaml_path.read_text())
    del data_yaml['nodes']['B']
    yaml_path.write_text(yaml.safe_dump(data_yaml))
    write_dot_from_yaml(yaml_path, dot_path, old_data=data)
    updated = yaml.safe_load(yaml_path.read_text())
    assert 'B' not in updated['nodes']
    assert 'B' not in updated['nodes']['A']['children']
