"""Shared installation of the package's global Git aliases."""

import subprocess


def install_git_alias(name, command, preserve_existing=False):
    """Install an alias, optionally retaining its exact configured command."""
    if preserve_existing:
        current = subprocess.run(
            ["git", "config", "--global", "--null", "--get", f"alias.{name}"],
            capture_output=True,
            text=True,
        )
        if current.returncode == 0 and current.stdout:
            # Remove only Git's terminator, preserving command whitespace.
            command = current.stdout[:-1]
        elif current.returncode not in (0, 1):
            raise SystemExit(
                f"Cannot read global alias.{name}: {current.stderr.strip()}"
            )
    try:
        subprocess.run(
            ["git", "config", "--global", f"alias.{name}", command],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            f"Cannot install global alias.{name}: {exc}"
        ) from None
    print(f"Installed global git alias: alias.{name} -> {command}")
