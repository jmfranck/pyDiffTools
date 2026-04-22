import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import urllib.request
import urllib.error

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


def _normalize_project_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _version_tuple(version):
    parts = [int(part) for part in re.findall(r"\d+", str(version))]
    return tuple(parts)


def _is_newer_version(latest_version, current_version):
    try:
        from packaging.version import Version

        return Version(latest_version) > Version(current_version)
    except Exception:
        latest_tuple = _version_tuple(latest_version)
        current_tuple = _version_tuple(current_version)
        width = max(len(latest_tuple), len(current_tuple))
        latest_tuple = latest_tuple + (0,) * (width - len(latest_tuple))
        current_tuple = current_tuple + (0,) * (width - len(current_tuple))
        return latest_tuple > current_tuple


def _read_project_version(pyproject_path, package_name):
    text = pyproject_path.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
        project = data.get("project", {})
        name = project.get("name")
        version = project.get("version")
        if name is None or version is None:
            return None
        if _normalize_project_name(name) != _normalize_project_name(
            package_name
        ):
            return None
        return str(version)

    in_project = False
    name = None
    version = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if not in_project or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key == "name":
            name = value
        elif key == "version":
            version = value
    if (
        name is None
        or version is None
        or _normalize_project_name(name) != _normalize_project_name(package_name)
    ):
        return None
    return version


def _source_tree_version(package_name):
    module_name = package_name.replace("-", "_").lower()
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None:
        return None
    origin = spec.origin
    if origin is None and spec.submodule_search_locations:
        origin = next(iter(spec.submodule_search_locations), None)
    if origin is None:
        return None

    path = Path(origin).resolve()
    if path.is_file():
        start = path.parent
    else:
        start = path
    for directory in [start, *start.parents]:
        pyproject_path = directory / "pyproject.toml"
        if pyproject_path.exists():
            return _read_project_version(pyproject_path, package_name)
    return None


def current_version(package_name):
    metadata_version = None
    try:
        metadata_version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None

    source_version = _source_tree_version(package_name)
    if source_version is not None and _is_newer_version(
        source_version, metadata_version
    ):
        return source_version
    return metadata_version


# Return the installed version, the latest version, and whether an update exists.
# Network errors and malformed responses are ignored so this never blocks the CLI
# when the network is down.
def check_update(package_name, timeout=1):
    installed_version = current_version(package_name)
    if installed_version is None:
        return None, None, False

    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return installed_version, None, False

    if "info" not in data or "version" not in data["info"]:
        return installed_version, None, False

    latest_version = data["info"]["version"]

    return (
        installed_version,
        latest_version,
        _is_newer_version(latest_version, installed_version),
    )
