"""Flowchart helpers for dot/yaml conversion and watching.

Heavy dependencies (like PyYAML) are imported lazily so unrelated CLI commands
can start up even when optional packages are absent.
"""

__all__ = ["IndentDumper", "load_graph_yaml", "write_dot_from_yaml", "dot_to_yaml", "watch_graph"]


def __getattr__(name):
    if name in ["IndentDumper", "load_graph_yaml", "write_dot_from_yaml"]:
        from .graph import IndentDumper, load_graph_yaml, write_dot_from_yaml

        return {
            "IndentDumper": IndentDumper,
            "load_graph_yaml": load_graph_yaml,
            "write_dot_from_yaml": write_dot_from_yaml,
        }[name]
    if name == "dot_to_yaml":
        from .dot_to_yaml import dot_to_yaml

        return dot_to_yaml
    if name == "watch_graph":
        from . import watch_graph

        return watch_graph
    raise AttributeError(name)
