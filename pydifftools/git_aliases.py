"""Global Git alias installation, incoming branch merges, and completion."""

import subprocess
import os
from pathlib import Path

from .command_registry import register_command


GIT_ALIASES = {
    "gd": '!f() { pydifft gd "$@"; }; f',
    "pd": '!f() { pydifft pd --git "$@"; }; f',
    "tree": '!f() { pydifft tree "$@"; }; f',
    "mergein": '!f() { pydifft mergein "$@"; }; f',
}


def install_git_alias(name, command, preserve_existing=False):
    """Install an alias and its completion, optionally retaining its value."""
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

    if name == "gd":
        # {{{ remind the user about the external difftool
        tool_cmd = subprocess.run(
            ["git", "config", "--global", "--get",
             "difftool.mygvim.cmd"],
            capture_output=True,
            text=True,
        )
        if tool_cmd.returncode != 0 or not tool_cmd.stdout.strip():
            print(
                "Reminder: configure difftool.mygvim.cmd so git "
                "difftool knows which GUI diff tool to launch."
            )
        # }}}
    elif name == "mergein":
        # {{{ install Bash's lazily loaded Git command completion
        completion_root = Path(
            os.environ.get("BASH_COMPLETION_USER_DIR")
            or str(
                Path(os.environ.get("XDG_DATA_HOME")
                     or Path.home() / ".local/share") / "bash-completion"
            )
        )
        target = completion_root / "completions" / "git-mergein"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                (Path(__file__).parent / "completions"
                 / "git-mergein").read_bytes()
            )
        except OSError as exc:
            raise SystemExit(
                f"Cannot install Bash completion at {target}: {exc}"
            ) from None
        print(f"Installed Bash completion: {target}")
        # }}}


@register_command(
    "fetch an incoming branch into its local branch and merge with --no-ff",
    description=(
        "Fetch REMOTE BRANCH:BRANCH without switching branches, then run "
        "git merge --no-ff BRANCH into the current branch.\n"
        "REMOTE defaults to origin. Local branch updates are not forced.\n"
        "Install git mergein with pydifft --add_to_git mergein."
    ),
    help={"remote": "Remote to fetch from (default: origin)."},
    argument_options={"branch": {"metavar": "BRANCH"}},
)
def mergein(branch, remote="origin"):
    """Update the incoming local branch, then merge into the current one."""
    try:
        valid = subprocess.run(
            ["git", "check-ref-format", f"refs/heads/{branch}"],
            capture_output=True,
        )
        if valid.returncode or branch.startswith("-"):
            raise SystemExit(f"mergein: invalid branch name: {branch}")
        subprocess.run(
            ["git", "fetch", "--", remote, f"{branch}:{branch}"], check=True,
        )
        subprocess.run(
            ["git", "merge", "--no-ff", "--", branch], check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
    except OSError as exc:
        raise SystemExit(f"mergein: {exc}") from None


def mergein_completer(prefix, parsed_args, **kwargs):
    """Complete configured remotes or their cached, nonsymbolic branches."""
    try:
        if kwargs["action"].dest == "remote":
            result = subprocess.run(
                ["git", "remote"], capture_output=True, text=True,
            )
            candidates = result.stdout.splitlines()
        else:
            remote = getattr(parsed_args, "remote", "origin")
            ref_prefix = f"refs/remotes/{remote}/"
            result = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname) %(symref)",
                 "--", ref_prefix],
                capture_output=True,
                text=True,
            )
            candidates = [
                line[len(ref_prefix):].rstrip()
                for line in result.stdout.splitlines()
                if line.startswith(ref_prefix) and line.endswith(" ")
                and line[len(ref_prefix):].rstrip() != "HEAD"
            ]
        return [name for name in candidates if name.startswith(prefix)]
    except OSError:
        return []
