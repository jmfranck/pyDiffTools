"""Render Markdown and LaTeX comparisons using the project diff style."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .command_registry import register_command


@register_command(
    "generate a PDF diff from two Markdown or TeX files",
    description=(
        "Compare OLD and NEW using mylatexdiff-preamble.sty. Write "
        "NEW_diff.tex beside NEW and compile NEW_diff.pdf unless "
        "--no-compile is supplied. Both inputs must be .md or both .tex."
    ),
    filename_extensions={"old": [".md", ".tex"], "new": [".md", ".tex"]},
    argument_options={
        "old": {"metavar": "OLD", "help": "Older document version."},
        "new": {"metavar": "NEW", "help": "Newer document version."},
        "no_compile": {
            "help": "Keep the diff TeX without compiling a PDF.",
        },
    },
)
def pd(old, new, no_compile=False):
    # {{{ validate inputs and locate the user's custom preamble
    old, new = Path(old).resolve(), Path(new).resolve()
    if old.suffix.lower() not in {".md", ".tex"}:
        raise SystemExit("pd: inputs must have .md or .tex extensions")
    if old.suffix.lower() != new.suffix.lower():
        raise SystemExit("pd: both inputs must have the same extension")
    for source in (old, new):
        if not source.is_file():
            raise SystemExit(f"pd: input file does not exist: {source}")
    output = new.with_name(new.stem + "_diff.tex")
    if output.resolve() in {old, new}:
        raise SystemExit("pd: the diff output would overwrite an input")
    required = ["latexdiff"]
    if old.suffix.lower() == ".md":
        required.extend(["pandoc", "pandoc-crossref"])
    for executable in required:
        if shutil.which(executable) is None:
            raise SystemExit(f"pd: {executable} is not on PATH")
    preamble = None
    for directory in (Path.cwd(), new.parent):
        candidate = directory / "mylatexdiff-preamble.sty"
        if candidate.is_file():
            preamble = candidate.resolve()
            break
    if preamble is None and shutil.which("kpsewhich") is not None:
        lookup = subprocess.run(
            ["kpsewhich", "mylatexdiff-preamble.sty"],
            capture_output=True,
            text=True,
        )
        if lookup.returncode == 0 and lookup.stdout.strip():
            candidate = Path(lookup.stdout.strip())
            if candidate.is_file():
                preamble = candidate.resolve()
    if preamble is None:
        raise SystemExit(
            "pd: cannot find mylatexdiff-preamble.sty in the current "
            "directory, beside NEW, or through kpsewhich"
        )
    # }}}

    stage = "preparing the comparison"
    try:
        with tempfile.TemporaryDirectory(prefix="pydifft-pd-") as temp:
            tex_inputs = [old, new]
            # {{{ convert Markdown without rewriting the source files
            if old.suffix.lower() == ".md":
                image_filter = Path(temp) / "absolute_images.lua"
                image_filter.write_text(
                    "function Image(image)\n"
                    "  if not image.src:match('^[%a][%w+.-]*:')\n"
                    "      and not pandoc.path.is_absolute(image.src) then\n"
                    "    image.src = pandoc.path.normalize(\n"
                    "      pandoc.path.join({\n"
                    "      pandoc.system.get_working_directory(), image.src\n"
                    "      }))\n"
                    "  end\n"
                    "  return image\n"
                    "end\n"
                    "-- Dollar delimiters work with soul highlighting.\n"
                    "function Math(math)\n"
                    "  if math.mathtype == 'InlineMath' then\n"
                    "    return pandoc.RawInline('latex',\n"
                    "      '$'..math.text..'$')\n"
                    "  end\n"
                    "end\n",
                    encoding="utf-8",
                )
                tex_inputs = []
                for label, source in zip(("old", "new"), (old, new)):
                    converted = Path(temp) / (label + ".tex")
                    stage = f"converting Markdown {source}"
                    subprocess.run(
                        [
                            "pandoc",
                            "--from=markdown",
                            "--to=latex",
                            "--standalone",
                            "--filter=pandoc-crossref",
                            "--citeproc",
                            "--lua-filter",
                            str(image_filter),
                            "--output",
                            str(converted),
                            str(source),
                        ],
                        cwd=source.parent,
                        check=True,
                    )
                    # Older crossref adds subfig even without subfigures.
                    # Keep its imports only when the document uses them.
                    latex = converted.read_text(encoding="utf-8")
                    if r"\subfloat" not in latex:
                        latex = latex.replace(
                            r"\@ifpackageloaded{subfig}{}"
                            r"{\usepackage{subfig}}",
                            "",
                        ).replace(
                            r"\captionsetup[subfloat]{margin=0.5em}",
                            "",
                        )
                        converted.write_text(latex, encoding="utf-8")
                    tex_inputs.append(converted)
            # }}}
            # {{{ preserve the legacy latexdiff options and sed transforms
            stage = "generating the TeX diff"
            diff = subprocess.run(
                [
                    "latexdiff",
                    "-p",
                    str(preamble),
                    "--append-textcmd",
                    "caption,intertext,ubpair,obpair,paragraph,textbf,textit,"
                    "section,subsection,subsubsection",
                    "--exclude-textcmd",
                    "john,bibcite",
                    "--append-safecmd",
                    "mbox,Big,big,frac,_,gamma,correltime,tau,xi,section,"
                    "subsection,subsubsection",
                    "--exclude-safecmd",
                    "bibcite",
                    *[str(source) for source in tex_inputs],
                ],
                stdout=subprocess.PIPE,
                check=True,
            )
            # sed replaces only the first match on each line.
            contents = b"\n".join(
                re.sub(
                    rb"(\\john\[[^]]*)(\\DIF)",
                    rb"\1\\protect\2",
                    line.replace(b"%DIF > REMOVE ", b"", 1).replace(
                        b"%REMOVE ",
                        b"",
                        1,
                    ),
                    count=1,
                )
                for line in diff.stdout.split(b"\n")
            ).replace(b"\r", b"")
            stage = f"writing {output}"
            with tempfile.NamedTemporaryFile(
                dir=output.parent,
                prefix=".pydifft-pd-",
                delete=False,
            ) as staged:
                staged_path = Path(staged.name)
                try:
                    staged.write(contents)
                    staged.close()
                    staged_path.replace(output)
                finally:
                    staged_path.unlink(missing_ok=True)
            print(f"TeX diff: {output}")
            # }}}

        # {{{ compile in the newer document's project directory
        if not no_compile:
            stage = f"compiling {output} (the diff TeX has been retained)"
            if shutil.which("latexmk") is None:
                raise SystemExit(
                    "pd: latexmk is not on PATH; the diff TeX has been "
                    "retained. Use --no-compile to generate only TeX."
                )
            subprocess.run(
                [
                    "latexmk",
                    "-pdf",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-synctex=1",
                    output.name,
                ],
                cwd=new.parent,
                check=True,
            )
            print(f"PDF diff: {output.with_suffix('.pdf')}")
        # }}}
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"pd: failed while {stage}: {exc}") from None
