"""Pandoc Word exports for manuscript profiles."""

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import os
from itertools import groupby
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from lxml import etree
import yaml

from .pandoc_filters import global_filters


FRONT = re.compile(
    r"\A\ufeff?---[^\S\n]*\n(.*?)\n(?:---|\.\.\.)[^\S\n]*(?:\n|$)", re.S,
)
COMMENT = re.compile(r"<([A-Za-z]{2})com>(.*?)</\1com>", re.S)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def word_export(source, baseline=None, target=None, legacy=False):
    source = Path(source).resolve()
    target = Path(target or source).resolve()
    current = target.read_text(encoding="utf-8")
    git_env = os.environ.copy()
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX",
                     "GIT_INDEX_FILE"):
        git_env.pop(variable, None)

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=source.parent, text=True,
            stderr=subprocess.DEVNULL, env=git_env,
        )

    path = source.name
    target_commit = None
    suffix = "generated"
    if baseline is not None:
        try:
            if source == target:
                if git("status", "--porcelain", "--untracked-files=all",
                       "--", path):
                    raise SystemExit(
                        f"wd: {source} has uncommitted changes. Commit the "
                        "Markdown file first, then rerun wd."
                    )
                target_commit = git("rev-parse", "HEAD").strip()
            else:
                target_commit = next(
                    commit for commit in git(
                        "rev-list", "--all", "--", path,
                    ).splitlines()
                    if git("show", f"{commit}:./{path}") == current
                )
            if git("show", f"{target_commit}:./{path}") != current:
                raise StopIteration
            suffix = git("rev-parse", "--short=8", target_commit).strip()
        except (subprocess.CalledProcessError, StopIteration):
            raise SystemExit(
                f"wd: no committed Git version found for {source}. "
                "Commit the Markdown file first, then rerun wd."
            ) from None
    if legacy:
        return False
    front = FRONT.match(source.read_text(encoding="utf-8"))
    settings = (yaml.safe_load(front[1]) or {}) if front else {}
    profile = settings.get("docx-defaults")
    if baseline is not None and profile is None:
        return False
    defaults = {}
    if profile is not None:
        if not isinstance(profile, str) or not profile:
            raise ValueError("docx-defaults must name a Pandoc defaults file")
        defaults = yaml.safe_load((source.parent / profile).read_text())
        if not isinstance(defaults, dict):
            raise ValueError("docx-defaults must contain a YAML mapping")
    postprocess = defaults.pop("docx-postprocess", None)
    defaults.pop("input-files", None)
    defaults.pop("output-file", None)
    defaults.setdefault(
        "from", "latex" if source.suffix == ".tex" else "markdown",
    )
    defaults.update(to="docx", standalone=True)
    shared = global_filters(settings, source)
    defaults["filters"] = shared + [
        entry for entry in defaults.get("filters", ["pandoc-crossref"])
        if not isinstance(entry, str)
        or str((source.parent / entry).resolve()) not in shared
    ]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dates = {}
    def comments_in(text):
        return [
            (
                match.start(), (match[1], match[2].strip()),
                text[max(match.start() - 100, 0):match.start()]
                + text[match.end():match.end() + 100],
            )
            for match in COMMENT.finditer(text)
        ]

    comments = comments_in(current)

    # {{{ Walk backward from the target snapshot until each comment changes.
    if comments:
        try:
            history = git(
                "log", "--first-parent", "--format=%H %cI",
                target_commit or "HEAD", "--", path,
            ).splitlines()
            active = {offset: (key, context)
                      for offset, key, context in comments}
            for row in history:
                commit, date = row.split()
                previous = comments_in(git("show", f"{commit}:./{path}"))
                candidates = sorted(
                    (
                        -SequenceMatcher(None, context, old_context).ratio(),
                        offset, index,
                    )
                    for offset, (key, context) in active.items()
                    for index, (_, old_key, old_context) in enumerate(previous)
                    if key == old_key
                )
                matched = {}
                used = set()
                for _, offset, index in candidates:
                    if offset not in matched and index not in used:
                        matched[offset] = previous[index][1:]
                        used.add(index)
                        dates[offset] = date
                active = matched
                if not active:
                    break
        except (subprocess.CalledProcessError, StopIteration):
            pass
    # }}}

    def render(match):
        key = match[1], match[2].strip()
        if match.start() not in dates:
            print(f"{source.name}: using export time for {key[0]} comment")
        body = " ".join(line.strip() for line in key[1].splitlines())
        return (
            f' [{body}]{{.comment-start id="{match.start()}" '
            f'author="{key[0]}" date="{dates.get(match.start(), now)}"}}'
            f'[]{{.comment-end id="{match.start()}"}} '
        )

    clean = source.with_stem(f"{source.stem}-{suffix}").with_suffix(".docx")
    tracked = source.with_name(source.stem + "-tracked.docx")
    with tempfile.TemporaryDirectory(dir=source.parent) as temp:
        tmp = Path(temp)
        config = tmp / "defaults.yaml"
        config.write_text(yaml.safe_dump(defaults), encoding="utf-8")
        for text, output in [
            (COMMENT.sub(render, current), tmp / clean.name),
            *([] if baseline is None else [(
                COMMENT.sub("", Path(baseline).read_text(encoding="utf-8")),
                tmp / "baseline.docx",
            )]),
        ]:
            subprocess.run(
                ["pandoc", "--defaults", str(config), "-o", str(output)],
                input=text, text=True, cwd=source.parent, check=True,
            )

        outputs = [clean]
        if baseline is not None:
            compare(
                tmp / "baseline.docx", tmp / clean.name,
                tmp / tracked.name, now,
            )
            outputs.append(tracked)
        for output in outputs:
            if postprocess:
                subprocess.run(
                    [sys.executable, postprocess, str(tmp / output.name)],
                    cwd=source.parent, check=True,
                )
            with ZipFile(tmp / output.name) as archive:
                document = etree.fromstring(archive.read("word/document.xml"))
                for tag in ("commentRangeStart", "commentRangeEnd",
                            "commentReference"):
                    if len(list(document.iter(W + tag))) != len(comments):
                        raise ValueError(
                            f"{output.name}: expected {len(comments)} {tag}s"
                        )
        for output in outputs:
            (tmp / output.name).replace(output)
            print(output)
    return True


# also used by: tests/cli/test_word_export.py
def compare(baseline, clean, output, date):
    part = "word/document.xml"
    with ZipFile(baseline) as old, ZipFile(clean) as new:
        old_body = etree.fromstring(old.read(part)).find(W + "body")
        document = etree.fromstring(new.read(part))
        body = document.find(W + "body")
        revision_id = 0
        relationships = "word/_rels/document.xml.rels"
        old_links, new_links = (
            {
                node.get("Id"): tuple(node.get(key) for key in
                                      ("Type", "Target", "TargetMode"))
                for node in etree.fromstring(package.read(relationships))
            } if relationships in package.namelist() else {}
            for package in (old, new)
        )
        link_ids = {link: identifier for identifier, link in new_links.items()}

        def remap(node):
            for element in node.iter():
                for attribute, value in element.attrib.items():
                    if attribute.startswith(REL):
                        link = old_links.get(value)
                        if link not in link_ids:
                            raise ValueError(
                                f"Baseline relationship {value} is missing "
                                "from the target DOCX"
                            )
                        element.set(attribute, link_ids[link])

        def mark(parent, kind):
            nonlocal revision_id
            revision_id += 1
            return etree.SubElement(parent, W + kind, {
                W + "id": str(revision_id), W + "author": "Comparison",
                W + "date": date,
            })

        def key(block):
            return block.tag, tuple(
                (node.tag, node.text) for node in block.iter()
                if node.text and node.tag.endswith("}t")
                and not node.text.isspace()
            )

        def wrap(node, kind):
            parent = node.getparent()
            position = parent.index(node)
            if kind == "del":
                for run in node.iter(W + "t"):
                    run.tag = W + "delText"
            revision = mark(parent, kind)
            revision.append(node)
            parent.insert(position, revision)

        def editable(node):
            return node.tag not in {
                W + "pPr", W + "commentRangeStart", W + "commentRangeEnd",
                W + "bookmarkStart", W + "bookmarkEnd",
            } and node.find(W + "commentReference") is None

        def revise(block, kind):
            if block.tag in {W + "tbl", W + "tr"}:
                rows = (
                    block.findall(W + "tr") if block.tag == W + "tbl"
                    else [block]
                )
                for row in rows:
                    props = row.find(W + "trPr")
                    if props is None:
                        props = etree.Element(W + "trPr")
                        row.insert(0, props)
                    mark(props, kind)
                return
            if block.tag != W + "p":
                raise ValueError(f"Unsupported changed Word block {block.tag}")
            props = block.find(W + "pPr")
            if props is None:
                props = etree.Element(W + "pPr")
                block.insert(0, props)
            run_props = props.find(W + "rPr")
            if run_props is None:
                run_props = etree.SubElement(props, W + "rPr")
            mark(run_props, kind)
            for node in list(block):
                if editable(node):
                    wrap(node, kind)

        def inline(old, new):
            # {{{ Match text independently of Pandoc's run boundaries.
            # Equations and runs with non-text children remain atomic.
            def tokens(para):
                result = []
                for node in filter(editable, para):
                    content = node.find(W + "t")
                    if node.tag != W + "r" or content is None or any(
                        child.tag not in {W + "rPr", W + "t"} for child in node
                    ) or len(node.findall(W + "t")) != 1 or not content.text:
                        result.append((node, 0, 0, etree.tostring(node)))
                        continue
                    props = node.find(W + "rPr")
                    style = etree.tostring(props) if props is not None else b""
                    result.extend(
                        (node, match.start(), match.end(),
                         (style, match[0]))
                        for match in re.finditer(
                            r"\w+|\s+|[^\w\s]", content.text,
                        )
                    )
                return result

            def fragments(tokens, ranges):
                # Materialize only the cuts required by the diff. Keep the
                # intact run whenever an opcode covers all its text.
                split = set()
                result = []
                for start, end in ranges:
                    pieces = []
                    for node, group in groupby(
                        tokens[start:end], key=lambda token: token[0],
                    ):
                        group = list(group)
                        first, last = group[0][1], group[-1][2]
                        if last and (
                            first or last < len(node.findtext(W + "t"))
                        ):
                            fragment = deepcopy(node)
                            text = fragment.find(W + "t")
                            text.text = text.text[first:last]
                            text.set(
                                "{http://www.w3.org/XML/1998/namespace}space",
                                "preserve",
                            )
                            node.addprevious(fragment)
                            split.add(node)
                            pieces.append(fragment)
                        else:
                            pieces.append(node)
                    result.append(pieces)
                for node in split:
                    node.getparent().remove(node)
                return result

            previous, current = tokens(old), tokens(new)
            opcodes = SequenceMatcher(
                None, [token[3] for token in previous],
                [token[3] for token in current], autojunk=False,
            ).get_opcodes()
            old_chunks = fragments(
                previous, [(a, b) for _, a, b, _, _ in opcodes],
            )
            new_chunks = fragments(
                current, [(c, d) for _, _, _, c, d in opcodes],
            )
            new_runs = [node for chunk in new_chunks for node in chunk]
            # }}}
            c = 0
            for (operation, _, _, _, _), old_runs, changed in zip(
                opcodes, old_chunks, new_chunks,
            ):
                if operation == "equal":
                    c += len(changed)
                    continue
                position = (
                    new.index(new_runs[c]) if c < len(new_runs) else len(new)
                )
                for node in old_runs:
                    remap(node)
                    new.insert(position, node)
                    wrap(node, "del")
                    position += 1
                for node in changed:
                    wrap(node, "ins")
                c += len(changed)

        # {{{ Keep the current package and interleave deleted baseline blocks.
        before = [node for node in old_body if node.tag != W + "sectPr"]
        after = [node for node in body if node.tag != W + "sectPr"]
        matcher = SequenceMatcher(
            None, list(map(key, before)), list(map(key, after)),
            autojunk=False,
        )
        for node in list(old_body.iter(W + "bookmarkStart")) + list(
            old_body.iter(W + "bookmarkEnd")
        ):
            node.getparent().remove(node)
        for operation, a, b, c, d in matcher.get_opcodes():
            if operation == "equal":
                continue
            if operation == "replace" and b - a == d - c and all(
                left.tag == right.tag == W + "p"
                and [(node.tag, dict(node.attrib)) for node in
                     left.iterfind(W + "pPr/*")]
                == [(node.tag, dict(node.attrib)) for node in
                    right.iterfind(W + "pPr/*")]
                for left, right in zip(before[a:b], after[c:d])
            ):
                for left, right in zip(before[a:b], after[c:d]):
                    inline(left, right)
                continue
            if operation == "replace" and b - a == d - c == 1:
                left, right = before[a], after[c]
                if left.tag == right.tag == W + "tbl":
                    old_rows = left.findall(W + "tr")
                    new_rows = right.findall(W + "tr")
                    if len(old_rows) == len(new_rows) and all(
                        len(row.findall(W + "tc"))
                        == len(other.findall(W + "tc"))
                        for row, other in zip(old_rows, new_rows)
                    ):
                        for row, other in zip(old_rows, new_rows):
                            if key(row) != key(other):
                                remap(row)
                                revise(row, "del")
                                revise(other, "ins")
                                right.insert(right.index(other), row)
                        continue
            position = (
                body.index(after[c]) if c < len(after) else len(after)
            )
            for block in before[a:b]:
                remap(block)
                revise(block, "del")
                body.insert(position, block)
                position += 1
            for block in after[c:d]:
                revise(block, "ins")
        # }}}
        with ZipFile(output, "w") as result:
            for entry in new.infolist():
                result.writestr(
                    entry, etree.tostring(document) if entry.filename == part
                    else new.read(entry),
                )
