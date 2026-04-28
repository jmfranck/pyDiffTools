import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import urllib.request
import urllib.error

def _version_tuple(version):
    parts = [int(part) for part in re.findall(r"\d+", str(version))]
    return tuple(parts)


# Return the installed version, the latest version, and whether an update exists.
# Network errors and malformed responses are ignored so this never blocks the CLI
# when the network is down.
def check_update(package_name, timeout=1):
    try:
        installed_version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None, None, False
    module_name = package_name.replace("-", "_").lower()
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        spec = None
    if spec is not None:
        origin = spec.origin
        if origin is None and spec.submodule_search_locations:
            origin = next(iter(spec.submodule_search_locations), None)
        if origin is not None:
            path = Path(origin).resolve()
            if path.is_file():
                path = path.parent
            for directory in [path, *path.parents]:
                pyproject_path = directory / "pyproject.toml"
                if not pyproject_path.exists():
                    continue
                text = pyproject_path.read_text(encoding="utf-8")
                match = re.search(
                    r'(?ms)^\[project\].*?^\s*name\s*=\s*["\']([^"\']+)["\']'
                    r'.*?^\s*version\s*=\s*["\']([^"\']+)["\']',
                    text,
                )
                if match is None:
                    break
                source_name, source_version = match.groups()
                if (
                    re.sub(r"[-_.]+", "-", source_name).lower()
                    == re.sub(r"[-_.]+", "-", package_name).lower()
                    and _version_tuple(source_version)
                    > _version_tuple(installed_version)
                ):
                    installed_version = source_version
                break

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
        _version_tuple(latest_version) > _version_tuple(installed_version),
    )
