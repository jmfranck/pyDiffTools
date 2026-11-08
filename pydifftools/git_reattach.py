"""Attach detached checkouts without changing the selected commits."""

from pathlib import Path
import subprocess

from .command_registry import register_command


def _git(path, *args, allowed=(0,)):
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True,
    )
    if result.returncode not in allowed:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.rstrip("\n")


@register_command(
    "reattach detached repositories to matching local or remote branches",
    description=(
        "Keep each checkout's current commit and attach a branch whose tip "
        "matches it exactly. Includes initialized submodules recursively. "
        "A remote-only match creates a local tracking branch. Existing "
        "branches are never reset. Ambiguous or unmatched checkouts stay "
        "detached. Cached remote branches are used unless --fetch is given."
    ),
    help={
        "path": "Repository or a directory inside it (default: current).",
        "no_recursive": "Only inspect this repository, not its submodules.",
        "fetch": "Fetch remote branches before looking for matches.",
        "dry_run": "Show proposed switches without changing anything.",
    },
)
def reattach(path=".", no_recursive=False, fetch=False, dry_run=False):
    """Find exact branch-tip matches, preserving commits and working files."""
    if fetch and dry_run:
        raise SystemExit("reattach: --fetch cannot be used with --dry-run")
    try:
        root = Path(_git(path, "rev-parse", "--show-toplevel"))
        paths = [root]
        if not no_recursive:
            children = _git(
                root, "submodule", "foreach", "--quiet", "--recursive",
                'printf "%s\\0" "$PWD"',
            )
            paths.extend(Path(p) for p in children.split("\0") if p)
        failed = False
        for checkout in paths:
            label = str(checkout)
            try:
                if _git(
                    checkout, "symbolic-ref", "--quiet", "HEAD",
                    allowed=(0, 1),
                ):
                    print(f"{label}: already on a branch; unchanged")
                    continue
                if fetch:
                    _git(checkout, "fetch", "--all", "--prune",
                         "--no-recurse-submodules")
                head = _git(checkout, "rev-parse", "HEAD")
                # {{{ ask Git for exact matches, excluding symbolic refs
                refs = _git(
                    checkout, "for-each-ref",
                    "--format=%(refname)%00%(symref)", "--points-at", head,
                    "refs/heads/", "refs/remotes/",
                )
                matches = [
                    line.split("\0")[0] for line in refs.splitlines()
                    if line.endswith("\0")
                ]
                local = [r for r in matches if r.startswith("refs/heads/")]
                remote = [r for r in matches
                          if r.startswith("refs/remotes/")]
                default = _git(
                    checkout, "symbolic-ref", "--quiet",
                    "refs/remotes/origin/HEAD", allowed=(0, 1),
                )
                default_name = default.removeprefix("refs/remotes/origin/")
                branch = None
                upstream = None
                if local:
                    preferred = "refs/heads/" + default_name
                    if preferred in local:
                        branch = default_name
                    elif len(local) == 1:
                        branch = local[0].removeprefix("refs/heads/")
                elif remote:
                    # Derive names from configured remotes, retaining slashes
                    # in branch names and allowing slashes in remote names.
                    remotes = sorted(
                        _git(checkout, "remote").splitlines(),
                        key=len, reverse=True,
                    )
                    candidates = {}
                    for ref in remote:
                        for name in remotes:
                            prefix = f"refs/remotes/{name}/"
                            if ref.startswith(prefix):
                                candidates[ref] = ref[len(prefix):]
                                break
                    if default in candidates:
                        upstream = default
                    elif len(candidates) == 1:
                        upstream = next(iter(candidates))
                    elif len(set(candidates.values())) == 1:
                        name = next(iter(candidates.values()))
                        preferred = "refs/remotes/origin/" + name
                        if preferred in candidates:
                            upstream = preferred
                    if upstream:
                        branch = candidates[upstream]
                        existing = _git(
                            checkout, "show-ref", "--verify", "--hash",
                            f"refs/heads/{branch}", allowed=(0, 1, 128),
                        )
                        if existing:
                            print(
                                f"{label}: local {branch} points elsewhere; "
                                "left detached without resetting it"
                            )
                            continue
                # }}}
                if branch is None:
                    reason = "ambiguous branch matches" if matches else (
                        "no branch tip matches this commit"
                    )
                    print(f"{label}: {reason}; left detached")
                    continue
                action = "create tracking branch" if upstream else "switch to"
                print(f"{label}: {action} {branch}")
                if not dry_run:
                    if upstream:
                        _git(checkout, "switch", "--track", "-c", branch,
                             upstream)
                    else:
                        _git(checkout, "switch", "--no-guess", "--", branch)
                    if _git(checkout, "rev-parse", "HEAD") != head:
                        raise RuntimeError("branch moved during reattachment")
            except RuntimeError as exc:
                print(f"{label}: {exc}")
                failed = True
        if failed:
            raise SystemExit(1)
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"reattach: {exc}") from None
