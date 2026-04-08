import types
from pydifftools.flowchart import watch_graph
from pydifftools.flowchart.graph import EmptyGraphYamlError


def test_yaml_write_does_not_loop(tmp_path, monkeypatch):
    yaml_file = tmp_path / "graph.yaml"
    yaml_file.write_text("")
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"
    calls = {"build": 0, "reload": 0}

    def fake_build(y, d, s, w, order_by_date=False, prev=None, target=None):
        calls["build"] += 1
        return {}

    def fake_reload(driver, svg):
        calls["reload"] += 1

    monkeypatch.setattr(watch_graph, "build_graph", fake_build)
    monkeypatch.setattr(watch_graph, "_reload_svg", fake_reload)

    handler = watch_graph.GraphEventHandler(
        yaml_file,
        dot_file,
        svg_file,
        None,
        wrap_width=55,
        data=None,
        debounce=0.5,
    )
    event = types.SimpleNamespace(src_path=str(yaml_file))
    handler.on_modified(event)
    handler.on_modified(event)
    assert calls["build"] == 1
    assert calls["reload"] == 1


def test_yaml_build_error_keeps_preview_open(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "graph.yaml"
    yaml_file.write_text("nodes:\n  task_a:\n    text: Task A\n")
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"

    def fake_build(*_args, **_kwargs):
        raise AttributeError("boom")

    close_calls = []

    monkeypatch.setattr(watch_graph, "build_graph", fake_build)
    monkeypatch.setattr(watch_graph, "close_chrome", close_calls.append)

    handler = watch_graph.GraphEventHandler(
        yaml_file,
        dot_file,
        svg_file,
        None,
        wrap_width=55,
        data=None,
        debounce=0.0,
    )
    handler.driver = object()
    event = types.SimpleNamespace(src_path=str(yaml_file))
    handler.on_modified(event)

    assert close_calls == []
    assert handler.driver is not None
    logs = capsys.readouterr().out
    assert "Graph build failed; keeping preview window open" in logs


def test_empty_yaml_closes_preview_window(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "graph.yaml"
    yaml_file.write_text("")
    dot_file = tmp_path / "graph.dot"
    svg_file = tmp_path / "graph.svg"

    def fake_build(*_args, **_kwargs):
        raise EmptyGraphYamlError("empty yaml")

    close_calls = []

    monkeypatch.setattr(watch_graph, "build_graph", fake_build)
    monkeypatch.setattr(watch_graph, "close_chrome", close_calls.append)

    handler = watch_graph.GraphEventHandler(
        yaml_file,
        dot_file,
        svg_file,
        None,
        wrap_width=55,
        data=None,
        debounce=0.0,
    )
    handler.driver = object()
    event = types.SimpleNamespace(src_path=str(yaml_file))
    handler.on_modified(event)

    assert close_calls
    assert handler.driver is None
    logs = capsys.readouterr().out
    assert "Graph YAML is empty; closing preview window." in logs
