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

from .line_alignment import minimal_opcodes
from .pandoc_filters import global_filters
from .wrap_sentences import classify_lines, markdown_blocks


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
    dirty = False
    try:
        if source == target:
            dirty = bool(git(
                "status", "--porcelain", "--untracked-files=all", "--", path,
            ))
            target_commit = git("rev-parse", "HEAD").strip()
        else:
            target_commit = next(
                commit for commit in git(
                    "rev-list", "--all", "--", path,
                ).splitlines()
                if git("show", f"{commit}:./{path}") == current
            )
        if not dirty and git("show", f"{target_commit}:./{path}") != current:
            dirty = True
        if dirty and baseline is not None:
            raise SystemExit(
                f"{source} has uncommitted changes. Commit the "
                "Markdown file first, then rerun the Word export."
            )
        suffix = git("rev-parse", "--short=8", target_commit).strip()
        if dirty:
            suffix += "-dirty"
    except (subprocess.CalledProcessError, StopIteration):
        raise SystemExit(
            f"No committed Git version found for {source}. "
            "Commit the Markdown file first, then rerun the Word export."
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
                target_commit, "--", path,
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

    if baseline is not None:
        # Compare manuscript source before invoking Pandoc. Keep paragraph
        # boundaries and protected Markdown syntax in the source sequence.
        def without_comments(manuscript):
            parts = []
            position = 0
            for comment in COMMENT.finditer(manuscript):
                start, end = comment.span()
                line = manuscript.rfind("\n", position, start) + 1
                if line == 0:
                    line = position
                newline = manuscript.find("\n", end)
                if newline < 0:
                    newline = len(manuscript)
                if not (manuscript[line:start].strip()
                        or manuscript[end:newline].strip()):
                    start, end = line, min(newline + 1, len(manuscript))
                parts.append(manuscript[position:start])
                position = end
            parts.append(manuscript[position:])
            return "".join(parts)

        baseline_text = without_comments(
            Path(baseline).read_text(encoding="utf-8")
        )
        source_words = []
        for manuscript in (baseline_text, without_comments(current)):
            words = []
            for block in markdown_blocks(manuscript.rstrip()):
                if block.kind == "raw":
                    words.append(repr(block.text))
                    continue
                # Preserve literal and structural Markdown that wmatch
                # excludes from prose wrapping. Keep the lexical tokens
                # as well, for correspondence with rendered text.
                words.extend(
                    "<literal>" + repr(line)
                    for prose, line in classify_lines(block.text, strict=False)
                    if not prose and line.strip()
                )
                for token in re.findall(
                    r"`+[^`\n]*`+|\w+|[^\w\s]|\s+", block.text,
                ):
                    if not token.isspace():
                        words.append(token)
                    elif token.count("\n") > 1:
                        words.append("<paragraph>")
                    elif "\n" in token and token.split("\n", 1)[0].endswith(
                        "  "
                    ):
                        words.append("<hardbreak>")
                    else:
                        words.append("<space>")
            source_words.append(words)
        source_hunks = minimal_opcodes(*source_words)

    clean = source.with_stem(f"{source.stem}-{suffix}").with_suffix(".docx")
    tracked = source.with_name(source.stem + "-tracked.docx")
    with tempfile.TemporaryDirectory(dir=source.parent) as temp:
        tmp = Path(temp)
        config = tmp / "defaults.yaml"
        config.write_text(yaml.safe_dump(defaults), encoding="utf-8")
        for text, output in [
            (COMMENT.sub(render, current), tmp / clean.name),
            *([] if baseline is None else [(
                baseline_text,
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
                tmp / tracked.name, now, (source_words, source_hunks),
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
def compare(baseline, clean, output, date, source_alignment=None):
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

        significant = {
            W + tag for tag in (
                "b", "i", "rStyle", "pStyle", "vertAlign", "br", "tab",
            )
        }

        def key(block):
            return block.tag, tuple(
                (node.tag, node.text, tuple(node.attrib.items()))
                for node in block.iter()
                if (
                    node.text and node.tag.endswith("}t")
                    and not node.text.isspace()
                ) or node.tag in significant
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

        def paragraph_mark(block, kind):
            props = block.find(W + "pPr")
            if props is None:
                props = etree.Element(W + "pPr")
                block.insert(0, props)
            run_props = props.find(W + "rPr")
            if run_props is None:
                run_props = etree.SubElement(props, W + "rPr")
            mark(run_props, kind)

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
            paragraph_mark(block, kind)
            for node in list(block):
                if editable(node):
                    wrap(node, kind)

        # {{{ Map stable source tokens onto rendered runs for inline diffing.
        def tokens(para):
            result = []
            for node in filter(editable, para):
                content = node.find(W + "t")
                if node.tag != W + "r" or content is None or any(
                    child.tag not in {W + "rPr", W + "t"} for child in node
                ) or len(node.findall(W + "t")) != 1 or not content.text or (
                    node.findtext(W + "rPr/" + W + "rStyle")
                    is not None and node.find(
                        W + "rPr/" + W + "rStyle"
                    ).get(W + "val") == "VerbatimChar"
                ):
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

        source_ids = {}
        if source_alignment is not None:
            words, hunks = source_alignment
            shared_ids = [{}, {}]
            for operation, a, b, c, _ in hunks:
                if operation == "equal":
                    shared_ids[0].update((i, i) for i in range(a, b))
                    shared_ids[1].update(
                        (j, i) for i, j in zip(range(a, b), range(c, c + b-a))
                    )
            projections = []
            for manuscript, ids, tree in zip(
                words, shared_ids, (old_body, body),
            ):
                visible = [
                    (node, start, key[1])
                    for para in tree.iter(W + "p")
                    for node, start, _, key in [
                        *tokens(para), (para, 0, 0, (None, "<paragraph>")),
                    ]
                    if isinstance(key, tuple) and not key[1].isspace()
                ]
                projection = {}
                indices = [i for i, word in enumerate(manuscript)
                           if word != "<space>"]
                for operation, a, b, c, _ in minimal_opcodes(
                    [manuscript[i] for i in indices],
                    [item[2] for item in visible],
                ):
                    if operation == "equal":
                        projection.update(
                            (visible[c + i - a][:2], ids[indices[i]])
                            for i in range(a, b) if indices[i] in ids
                        )
                projections.append(projection)
            common = (
                set(projections[0].values()) & set(projections[1].values())
            )
            for projection in projections:
                source_ids.update(
                    (key, value) for key, value in projection.items()
                    if value in common
                )
        # }}}

        def inline(old, new):
            # {{{ Align words, equations and paragraph breaks independently
            # of the run boundaries chosen by the Word writer.
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

            def paragraph_tokens(paragraphs):
                return [
                    token for para in paragraphs
                    for token in [*tokens(para), (para, 0, 0, "paragraph")]
                ]

            def identity(token):
                node, start, _, key = token
                source_id = source_ids.get((node, start))
                return key if source_id is None else (key, source_id)

            previous, current = map(paragraph_tokens, (old, new))
            opcodes = SequenceMatcher(
                None, list(map(identity, previous)),
                list(map(identity, current)), autojunk=False,
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
            for (operation, a, b, start, stop), old_runs, changed in zip(
                opcodes, old_chunks, new_chunks,
            ):
                if operation == "equal":
                    for old_mark, new_mark in zip(
                        previous[a:b], current[start:stop],
                    ):
                        if old_mark[3] != "paragraph":
                            continue
                        left = old_mark[0].find(W + "pPr")
                        right = new_mark[0].find(W + "pPr")
                        before_props, after_props = (
                            etree.tostring(props) if props is not None else b""
                            for props in (left, right)
                        )
                        if before_props == after_props:
                            continue
                        if right is None:
                            right = etree.Element(W + "pPr")
                            new_mark[0].insert(0, right)
                        change = mark(right, "pPrChange")
                        change.append(
                            deepcopy(left) if left is not None
                            else etree.Element(W + "pPr")
                        )
                    c += len(changed)
                    continue
                # An anchor can introduce a spare space in the rendered DOCX.
                # Retain the target spacing unless a word or break changed.
                if all(
                    isinstance(token[3], tuple) and token[3][1] == " "
                    for token in previous[a:b] + current[start:stop]
                ):
                    c += len(changed)
                    continue
                if operation == "replace" and len(old_runs) == len(changed):
                    pairs = list(zip(old_runs, changed))
                    if all(
                        left.tag == right.tag == W + "r"
                        and left.findtext(W + "t") == right.findtext(W + "t")
                        and left.findtext(W + "t")
                        and all(child.tag in {W + "rPr", W + "t"}
                                for run in (left, right) for child in run)
                        for left, right in pairs
                    ):
                        for left, right in pairs:
                            props = right.find(W + "rPr")
                            if props is None:
                                props = etree.Element(W + "rPr")
                                right.insert(0, props)
                            old_props = left.find(W + "rPr")
                            mark(props, "rPrChange").append(
                                deepcopy(old_props) if old_props is not None
                                else etree.Element(W + "rPr")
                            )
                        c += len(changed)
                        continue
                anchor = new_runs[c] if c < len(new_runs) else new[-1]
                for node in old_runs:
                    paragraph = (
                        anchor if anchor.tag == W + "p"
                        else anchor.getparent()
                    )
                    if node.tag == W + "p":
                        if anchor.tag == W + "p":
                            split = etree.Element(W + "p")
                            paragraph.addnext(split)
                            anchor = split
                        else:
                            split = etree.Element(W + "p")
                            props = paragraph.find(W + "pPr")
                            if props is not None:
                                split.append(deepcopy(props))
                            for child in list(paragraph)[
                                paragraph.index(anchor):
                            ]:
                                split.append(child)
                            paragraph.addnext(split)
                        paragraph_mark(paragraph, "del")
                        continue
                    remap(node)
                    position = (
                        len(paragraph) if anchor.tag == W + "p"
                        else paragraph.index(anchor)
                    )
                    paragraph.insert(position, node)
                    wrap(node, "del")
                for node in changed:
                    if node.tag == W + "p":
                        paragraph_mark(node, "ins")
                    else:
                        wrap(node, "ins")
                c += len(changed)

        # {{{ Keep the current package and interleave deleted baseline blocks.
        structural = {
            W + tag for tag in ("sectPr", "bookmarkStart", "bookmarkEnd")
        }
        before = [node for node in old_body if node.tag not in structural]
        after = [
            node for node in body if node.tag not in structural and not (
                node.tag == W + "p"
                and node.find(W + "commentRangeStart") is not None
                and not any(editable(child) for child in node)
            )
        ]
        matcher = SequenceMatcher(
            None, list(map(key, before)), list(map(key, after)),
            autojunk=False,
        )
        for node in list(old_body.iter(W + "bookmarkStart")) + list(
            old_body.iter(W + "bookmarkEnd")
        ):
            node.getparent().remove(node)
        # Split mixed replacements at structural barriers. In particular a
        # rewritten table must not cause its caption to lose prose alignment.
        operations = []
        for operation, a, b, c, d in matcher.get_opcodes():
            if operation != "replace":
                operations.append((operation, a, b, c, d))
                continue
            groups = [
                [(tag, list(indices)) for tag, indices in groupby(
                    range(start, end),
                    key=lambda i: nodes[i].tag,
                )]
                for nodes, start, end in ((before, a, b), (after, c, d))
            ]
            left, right = groups
            structure = SequenceMatcher(
                None, [tag for tag, _ in left], [tag for tag, _ in right],
                autojunk=False,
            )
            for kind, i, j, k, l in structure.get_opcodes():
                x = left[i][1][0] if i < len(left) else b
                y = right[k][1][0] if k < len(right) else d
                if kind == "equal":
                    operations.extend(
                        ("replace", old_group[0], old_group[-1] + 1,
                         new_group[0], new_group[-1] + 1)
                        for (_, old_group), (_, new_group) in zip(
                            left[i:j], right[k:l],
                        )
                    )
                else:
                    operations.append((
                        kind, x, left[j-1][1][-1] + 1 if j > i else x,
                        y, right[l-1][1][-1] + 1 if l > k else y,
                    ))
        if source_alignment is not None and all(
            operation == "equal" for operation, *_ in source_alignment[1]
        ):
            operations = []

        for operation, a, b, c, d in operations:
            if operation == "equal":
                continue
            if operation == "replace" and all(
                node.tag == W + "p" for node in before[a:b] + after[c:d]
            ):
                inline(before[a:b], after[c:d])
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
