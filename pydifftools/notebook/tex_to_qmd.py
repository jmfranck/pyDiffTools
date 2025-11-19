#!/usr/bin/env python3
"""this script has been entirely vibe-coded based on the tex example included
in the repo!"""

import re
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

from pydifftools.command_registry import register_command


def find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Return index of matching close_ch for open_ch at *start* or -1."""
    depth = 1
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def preprocess_latex(src: str) -> str:
    """Convert custom environments and observation macros before pandoc."""

    def repl_python(m: re.Match) -> str:
        """Preserve python blocks exactly using markers."""
        code = m.group(1)
        return (
            "\\begin{verbatim}\n%%PYTHON_START%%\n"
            + code
            + "%%PYTHON_END%%\n\\end{verbatim}"
        )

    def repl_verbatim(m: re.Match) -> str:
        """Mark generic verbatim blocks for fenced conversion."""
        newline = m.group(1)
        body = m.group(2)
        if "%%PYTHON_START%%" in body:
            return m.group(0)
        return (
            f"\\begin{{verbatim}}{newline}%%VERBATIM_START%%\n"
            + body
            + "%%VERBATIM_END%%\n\\end{verbatim}"
        )

    # replace python environment with verbatim + markers without touching
    # the whitespace contained in the block
    src = re.sub(
        r"\\begin{python}(?:\[[^\]]*\])?\n(.*?)\\end{python}",
        repl_python,
        src,
        flags=re.S,
    )

    # mark standard verbatim blocks so they convert to fenced code later
    src = re.sub(
        r"\\begin{verbatim}(\n?)(.*?)\\end{verbatim}",
        repl_verbatim,
        src,
        flags=re.S,
    )

    # convert err environment so pandoc will parse inside while preserving
    # the whitespace exactly
    src = re.sub(
        r"\\begin{err}\n?(.*?)\\end{err}",
        lambda m: f"<err>{m.group(1)}</err>",
        src,
        flags=re.S,
    )

    # handle \o[...]{} and \o{} observations
    out = []
    i = 0
    while True:
        idx_bracket = src.find("\\o[", i)
        idx_brace = src.find("\\o{", i)
        idxs = [x for x in (idx_bracket, idx_brace) if x != -1]
        idx = min(idxs) if idxs else -1
        if idx == -1:
            out.append(src[i:])
            break
        out.append(src[i:idx])
        j = idx + 2
        attrs = ""
        if j < len(src) and src[j] == "[":
            end_attrs = find_matching(src, j, "[", "]")
            if end_attrs == -1:
                out.append(src[idx:])
                break
            attrs = src[j + 1 : end_attrs]
            j = end_attrs + 1
        if j >= len(src) or src[j] != "{":
            out.append(src[idx : idx + 2])
            i = idx + 2
            continue
        end_body = find_matching(src, j, "{", "}")
        if end_body == -1:
            out.append(src[idx:])
            break
        body = src[j + 1 : end_body]
        j = end_body + 1
        if attrs:
            m = re.match(r"(.*?)\s*(\(([^)]+)\))?$", attrs.strip())
            time = m.group(1).strip() if m else attrs.strip()
            author = m.group(3) if m else None
            tag = (
                f'<obs time="{time}"'
                + (f' author="{author}"' if author else "")
                + f">{body}</obs>"
            )
        else:
            tag = f"<obs>{body}</obs>"
        out.append(tag)
        i = j
    return "".join(out)


def clean_html_escapes(text: str) -> str:
    return text.replace("\\<", "<").replace("\\>", ">").replace('\\"', '"')


def finalize_markers(text: str) -> str:
    lines = []
    in_py = False
    need_reset = False
    in_verb = False
    for line in text.splitlines(keepends=True):
        if re.match(r"^\s*%%PYTHON_START%%", line):
            lines.append("```{python}\n")
            in_py = True
            need_reset = True
            continue
        if re.match(r"^\s*%%PYTHON_END%%", line):
            lines.append("```\n")
            in_py = False
            continue
        if re.match(r"^\s*%%VERBATIM_START%%", line):
            lines.append("```\n")
            in_verb = True
            continue
        if re.match(r"^\s*%%VERBATIM_END%%", line):
            lines.append("```\n")
            in_verb = False
            continue
        if in_py:
            stripped = line[4:] if line.startswith("    ") else line
            if need_reset:
                if stripped.lstrip().startswith("%reset"):
                    lines.append(stripped)
                else:
                    lines.append("%reset -f\n")
                    lines.append(stripped)
                need_reset = False
            else:
                lines.append(stripped)
        elif in_verb and line.startswith("    "):
            lines.append(line[4:])
        else:
            lines.append(line)
    return "".join(lines)


def format_observations(text: str) -> str:
    """Ensure observation tags sit on a single line without altering
    content."""

    obs_re = re.compile(r"(<obs[^>]*>)(.*?)(</obs>)", flags=re.S)

    def repl(match: re.Match) -> str:
        open_tag = match.group(1).strip()
        body = match.group(2)
        close_tag = match.group(3).strip()
        # trim newlines that may surround the body but keep internal whitespace
        body = body.lstrip("\n").rstrip("\n")
        return f"{open_tag}{body}{close_tag}"

    return obs_re.sub(repl, text)


def format_tags(text: str, indent_str: str = "  ") -> str:
    """Format <err> blocks with indentation and tidy <obs> tags."""
    text = format_observations(text)
    # normalize whitespace around err tags
    text = re.sub(r"<err>[ \t]*\n+", "<err>\n", text)
    text = re.sub(r"<err>[ \t]+", "<err>\n", text)
    text = re.sub(r"</err>[ \t]+", "</err>", text)
    # ensure opening obs tags start on a new line without collapsing blank
    # lines
    text = re.sub(r"(\n+)[ \t]*(<obs)", r"\1\2", text)
    text = re.sub(r"(?<!^)(?<!\n)(<obs)", r"\n\1", text)
    # ensure a newline after closing obs tags but keep extra blank lines
    text = re.sub(r"</obs>[ \t]+", "</obs>", text)
    text = re.sub(r"</obs>(?!\n)", "</obs>\n", text)
    pattern = re.compile(r"(<err>|</err>)")
    parts = pattern.split(text)
    out = []
    indent = 0
    prev_tag = None
    for part in parts:
        if not part:
            continue
        if part == "<err>":
            if out and not out[-1].endswith("\n"):
                out[-1] = out[-1].rstrip() + "\n"
            out.append(indent_str * indent + "<err>\n")
            indent += 1
            prev_tag = "<err>"
        elif part == "</err>":
            if out and not out[-1].endswith("\n"):
                out[-1] = out[-1].rstrip() + "\n"
            indent -= 1
            out.append(indent_str * indent + "</err>\n")
            prev_tag = "</err>"
        else:
            if prev_tag in ("<err>", "</err>") and part.startswith("\n"):
                part = part[1:]
            lines = part.splitlines(True)
            for line in lines:
                if line.strip():
                    out.append(indent_str * indent + line)
                else:
                    out.append(line)
            prev_tag = None
    formatted = "".join(out)
    return re.sub(r"[ \t]+(?=\n)", "", formatted)


@register_command(
    "Convert LaTeX sources to Quarto Markdown (.qmd) files",
    help={"tex": "Input .tex file to convert"},
)
def tex2qmd(tex):
    """Convert ``tex`` to a .qmd file and return the output path."""

    inp = Path(tex)
    if not inp.exists():
        print(f"File not found: {inp}", file=sys.stderr)
        sys.exit(1)

    base = inp.with_suffix("")
    src = inp.read_text()
    pre_content = preprocess_latex(src)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tex") as pre:
        pre.write(pre_content.encode())
        pre_path = pre.name

    mid_fd, mid_path = tempfile.mkstemp()
    Path(mid_path).unlink()  # we just want the name; pandoc will create it

    try:
        # Prefer Quarto's bundled pandoc when available so the conversion
        # matches Quarto defaults, but fall back to a standalone pandoc
        # installation when Quarto is not on PATH.
        quarto = shutil.which("quarto")
        if quarto:
            cmd = [quarto, "pandoc"]
        else:
            cmd = ["pandoc"]
        cmd += [
            pre_path,
            "-f",
            "latex",
            "-t",
            "markdown",
            "--wrap=none",
            "-o",
            mid_path,
        ]
        subprocess.run(cmd, check=True)
    finally:
        Path(pre_path).unlink(missing_ok=True)

    mid_text = Path(mid_path).read_text()
    Path(mid_path).unlink(missing_ok=True)

    clean_text = clean_html_escapes(mid_text)
    final_text = finalize_markers(clean_text)
    formatted = format_tags(final_text)
    out_path = base.with_suffix(".qmd")
    out_path.write_text(formatted)
    print(f"Wrote {out_path}")
    return out_path


def main():
    if len(sys.argv) != 2:
        print("Usage: tex_to_qmd.py file.tex", file=sys.stderr)
        sys.exit(1)
    tex2qmd(sys.argv[1])


if __name__ == "__main__":
    main()


# Maintain the previous helper name for any existing imports.
convert_tex_to_qmd = tex2qmd
