"""Filter declarations shared by preview and Word export."""

from pathlib import Path


def global_filters(metadata, source):
    if not isinstance(metadata, dict):
        return []
    key = "global-filters" if "global-filters" in metadata else (
        "filters-before-crossref"
    )
    values = metadata.get(key, [])
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValueError(f"{key} must be a list of file paths in {source}")
    paths = {}
    for value in values:
        path = (Path(source).resolve().parent / value).resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"{key} file not found: {value!r} (resolved to {path})"
            )
        paths[str(path)] = None
    return list(paths)
