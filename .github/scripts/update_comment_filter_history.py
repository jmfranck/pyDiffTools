"""Refresh the packaged helper hashes from all available Git history.

Run from any directory with:
    python .github/scripts/update_comment_filter_history.py
"""

import hashlib
import json
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    history = {}
    for logical_name, mode, name in (
        ("comment_tags.lua", "default", "comment_tags.lua"),
        ("comment_tags.lua", "margin", "comment_tags_margin.lua"),
        ("comment_tags.lua", "none", "comment_tags_no_comments.lua"),
        ("comments.css", "shared", "comments.css"),
        ("comments_author_colors.css", "shared", "comments_author_colors.css"),
        ("comment_toggle.js", "shared", "comment_toggle.js"),
    ):
        versions = history.setdefault(logical_name, {})
        renamed_paths = subprocess.check_output(
            ["git", "log", "--follow", "--format=", "--name-only",
             "--all", "--", f"pydifftools/{name}"],
            cwd=root, text=True,
        )
        paths = sorted({
            f"pydifftools/{name}", name,
            *(line for line in renamed_paths.splitlines() if line.strip()),
        })
        # --follow discovers former names but can simplify away branches.
        # Enumerate all history for those paths separately, including merges.
        commits = subprocess.check_output(
            ["git", "log", "--all", "--full-history", "--format=%H",
             "--", *paths], cwd=root, text=True,
        )
        for commit in commits.splitlines():
            for path in paths:
                blob = subprocess.run(
                    ["git", "show", f"{commit}:{path}"], cwd=root,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                if blob.returncode:
                    continue  # A deletion has no filter content to remember.
                content = blob.stdout.replace(b"\r\n", b"\n").replace(
                    b"\r", b"\n"
                )
                digest = hashlib.sha256(content).hexdigest()
                versions.setdefault(digest, {
                    "mode": mode, "commit": commit, "path": path,
                })
    destination = root / "pydifftools/comment_filter_history.json"
    destination.write_text(
        json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    count = sum(len(versions) for versions in history.values())
    print(f"Recorded {count} helper hashes in {destination}")


if __name__ == "__main__":
    main()
