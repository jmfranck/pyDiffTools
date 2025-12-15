import importlib.metadata
import json
import urllib.request
import urllib.error


# Return the installed version, the latest version, and whether an update exists.
# Network errors and malformed responses are ignored so this never blocks the CLI
# when the network is down.
def check_update(package_name, timeout=1):
    current_version = None
    try:
        current_version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None, None, False

    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return current_version, None, False

    if "info" not in data or "version" not in data["info"]:
        return current_version, None, False

    return (
        current_version,
        data["info"]["version"],
        current_version != data["info"]["version"],
    )
