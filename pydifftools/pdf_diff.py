"""Render Markdown and LaTeX comparisons using the project diff style."""

from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from .command_registry import register_command
from .git_aliases import install_git_alias


@register_command(
    "generate a PDF diff from two Markdown or TeX files",
    description=(
        "Compare OLD and NEW using mylatexdiff-preamble.sty. Write "
        "NEW_diff.tex beside NEW and compile NEW_diff.pdf unless "
        "--no-compile is supplied. Both inputs must be .md or both .tex.\n\n"
        "Run pydifft pd --add-to-git to install git pd.\n"
        "Then git pd REV -- FILE compares REV with the working file;\n"
        "git pd also accepts other git diff arguments and --no-compile."
    ),
    filename_extensions={"old": [".md", ".tex"], "new": [".md", ".tex"]},
    argument_options={
        "old": {
            "metavar": "OLD",
            "help": "Older document version.",
            "nargs": "?",
            "default": None,
        },
        "new": {
            "metavar": "NEW",
            "help": "Newer document version.",
            "nargs": "?",
            "default": None,
        },
        "no_compile": {
            "help": "Keep the diff TeX without compiling a PDF.",
        },
        "add_to_git": {
            "help": "Install or update the global git pd alias.",
        },
    },
)
def pd(old, new, no_compile=False, add_to_git=False):
    if add_to_git:
        if old is not None or new is not None or no_compile:
            raise SystemExit("pd: --add-to-git does not take diff arguments")
        install_git_alias("pd", '!f() { pydifft pd --git "$@"; }; f')
        return
    if old is None or new is None:
        raise SystemExit("pd: provide OLD and NEW, or use --add-to-git")
    render_pdf_diff(old, new, no_compile=no_compile)


def render_pdf_diff(old, new, no_compile=False, output=None, source_dirs=None):
    """Render file inputs or Git snapshots into a persistent output path."""
    # {{{ validate inputs and locate the user's custom preamble
    old, new = Path(old).resolve(), Path(new).resolve()
    if old.suffix.lower() not in {".md", ".tex"}:
        raise SystemExit("pd: inputs must have .md or .tex extensions")
    if old.suffix.lower() != new.suffix.lower():
        raise SystemExit("pd: both inputs must have the same extension")
    for source in (old, new):
        if not source.is_file():
            raise SystemExit(f"pd: input file does not exist: {source}")
    output = (
        Path(output).resolve()
        if output is not None
        else new.with_name(new.stem + "_diff.tex")
    )
    if output.resolve() in {old, new}:
        raise SystemExit("pd: the diff output would overwrite an input")
    if source_dirs is None:
        source_dirs = (old.parent, new.parent)
    required = ["latexdiff"]
    if old.suffix.lower() == ".md":
        required.extend(["pandoc", "pandoc-crossref"])
    for executable in required:
        if shutil.which(executable) is None:
            raise SystemExit(f"pd: {executable} is not on PATH")
    preamble = None
    for directory in (Path.cwd(), output.parent):
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
                # Mark Pandoc's highlighting definitions so deletions can
                # retain them even if NEW contains no highlighted code.
                stage = "reading the Pandoc LaTeX template"
                template = Path(temp) / "template.tex"
                default_template = subprocess.run(
                    ["pandoc", "--print-default-template=latex"],
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout
                template.write_bytes(
                    default_template.replace(
                        b"$highlighting-macros$",
                        b"% PYDIFFT HIGHLIGHT START\n$highlighting-macros$\n"
                        b"% PYDIFFT HIGHLIGHT END",
                    )
                )
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
                for label, source, directory in zip(
                    ("old", "new"),
                    (old, new),
                    source_dirs,
                ):
                    converted = Path(temp) / (label + ".tex")
                    stage = f"converting Markdown {source}"
                    subprocess.run(
                        [
                            "pandoc",
                            "--from=markdown",
                            "--to=latex",
                            "--standalone",
                            "--template",
                            str(template),
                            "--filter=pandoc-crossref",
                            "--citeproc",
                            "--lua-filter",
                            str(image_filter),
                            "--output",
                            str(converted),
                            str(source),
                        ],
                        cwd=directory,
                        check=True,
                    )
                    # Older crossref adds subfig even without subfigures.
                    # Keep its imports only when the document uses them.
                    latex = converted.read_text(encoding="utf-8")
                    # Keep Pandoc's citation anchors from being parsed as
                    # prose: latexdiff otherwise marks the TeX keyword pre.
                    latex = latex.replace(
                        r"\leavevmode\vadjust pre{\hypertarget",
                        r"\leavevmode{\hypertarget",
                    )
                    if r"\subfloat" not in latex:
                        latex = latex.replace(
                            r"\@ifpackageloaded{subfig}{}"
                            r"{\usepackage{subfig}}",
                            "",
                        ).replace(
                            r"\captionsetup[subfloat]{margin=0.5em}",
                            "",
                        )
                    # Code uses line-based diff markup, with highlighting
                    # kept separate from the custom prose highlighting.
                    # Custom preambles can omit its modification markers
                    # or cause latexdiff to hide deleted code by default.
                    latex = latex.replace(
                        r"\begin{document}",
                        "\\providecommand{\\DIFmodbegin}{}\n"
                        "\\providecommand{\\DIFmodend}{}\n"
                        "\\newcommand{\\PydifftCodeAdd}[1]{%\n"
                        "\\makebox[0pt][r]{\\textcolor{blue}{+}"
                        "\\hspace{0.5em}}%\n"
                        "\\begingroup\\setlength{\\fboxsep}{0pt}%\n"
                        "\\colorbox{yellow!25}{\\strut#1}\\endgroup}\n"
                        "\\newcommand{\\PydifftCodeDel}[1]{%\n"
                        "\\makebox[0pt][r]{\\textcolor{red}{-}"
                        "\\hspace{0.5em}}%\n"
                        "\\begingroup\\setlength{\\fboxsep}{0pt}%\n"
                        "\\colorbox{red!10}{\\strut#1}\\endgroup}\n"
                        "\\AtBeginDocument{\\lstdefinelanguage{DIFcode}{\n"
                        r"moredelim=[il][\color{red}]{\%DIF\ <\ },"
                        "\n"
                        r"moredelim=[il][\color{blue}]{\%DIF\ >\ }"
                        "\n}}\n"
                        r"\begin{document}",
                        1,
                    )
                    converted.write_text(latex, encoding="utf-8")
                    tex_inputs.append(converted)
                converted_sources = [
                    source.read_bytes() for source in tex_inputs
                ]
                highlighting = [
                    re.search(
                        rb"% PYDIFFT HIGHLIGHT START\n.*?"
                        rb"% PYDIFFT HIGHLIGHT END",
                        source,
                        re.DOTALL | re.MULTILINE,
                    )
                    for source in converted_sources
                ]
                for index, header in enumerate(highlighting):
                    if header is None and highlighting[1 - index]:
                        tex_inputs[index].write_bytes(
                            converted_sources[index].replace(
                                rb"\begin{document}",
                                highlighting[1 - index][0]
                                + b"\n"
                                + rb"\begin{document}",
                                1,
                            )
                        )
            # }}}
            # {{{ compare additions and deletions against an empty body
            for index, source in enumerate((old, new)):
                if source.stat().st_size == 0:
                    counterpart = tex_inputs[1 - index].read_bytes()
                    empty_document, count = re.subn(
                        rb"(\\begin\{document\}).*?(\\end\{document\})",
                        rb"\1\n\2",
                        counterpart,
                        count=1,
                        flags=re.DOTALL,
                    )
                    if count:
                        empty = Path(temp) / f"empty-{index}.tex"
                        empty.write_bytes(empty_document)
                        tex_inputs[index] = empty
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
                    *(
                        ["--add-to-config", "VERBATIMLINEENV=Highlighting"]
                        if old.suffix.lower() == ".md"
                        else []
                    ),
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
            # {{{ mark highlighted code without crossing verbatim lines
            if old.suffix.lower() == ".md":
                for block in reversed(
                    list(
                        re.finditer(
                            rb"^(\\begin\{Highlighting\})(\[[^\n]*?\])?"
                            rb"(\n)(.*?)(\\end\{Highlighting\})",
                            contents,
                            re.DOTALL | re.MULTILINE,
                        )
                    )
                ):
                    options = (
                        (block[2] or b"")
                        .replace(
                            b",alsolanguage=DIFcode",
                            b"",
                        )
                        .replace(b"alsolanguage=DIFcode", b"")
                    )
                    lines = []
                    for line in block[4].split(b"\n"):
                        for prefix, command in (
                            (b"%DIF < ", rb"\PydifftCodeDel"),
                            (b"%DIF > ", rb"\PydifftCodeAdd"),
                        ):
                            if line.startswith(prefix):
                                text = line[len(prefix) :]
                                # latexdiff adds '-' for a changed empty line.
                                if text == b"-":
                                    text = b""
                                line = command + b"{" + text + b"}"
                                break
                        lines.append(line)
                    replacement = (
                        block[1]
                        + options
                        + block[3]
                        + b"\n".join(lines)
                        + block[5]
                    )
                    contents = (
                        contents[: block.start()]
                        + replacement
                        + contents[block.end() :]
                    )
            # }}}
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

        # {{{ run TeX and bibliography passes until references settle
        if not no_compile:
            stage = f"compiling {output} (the diff TeX has been retained)"
            if shutil.which("pdflatex") is None:
                raise SystemExit(
                    "pd: pdflatex is not on PATH; the diff TeX has been "
                    "retained. Use --no-compile to generate only TeX."
                )
            previous_state = None
            bibliography_state = None
            for pass_number in range(6):
                bcf = output.with_suffix(".bcf")
                previous_bcf = (
                    (bcf.stat().st_mtime_ns, bcf.read_bytes())
                    if bcf.exists()
                    else None
                )
                subprocess.run(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-synctex=1",
                        output.name,
                    ],
                    cwd=output.parent,
                    check=True,
                )
                # Read only the aux files belonging to this document,
                # including those produced by its \include commands.
                aux_files = {}
                pending = [output.with_suffix(".aux")]
                while pending:
                    aux = pending.pop().resolve()
                    if aux in aux_files or not aux.is_file():
                        continue
                    aux_files[aux] = aux.read_bytes()
                    pending.extend(
                        output.parent / os.fsdecode(name)
                        for name in re.findall(
                            rb"\\@input\{([^}]+)\}", aux_files[aux]
                        )
                    )
                bibliography = None
                if (
                    bcf.exists()
                    and (bcf.stat().st_mtime_ns, bcf.read_bytes())
                    != previous_bcf
                ):
                    bibliography = ("biber", bcf.read_bytes())
                else:
                    bib_commands = tuple(
                        command
                        for contents in aux_files.values()
                        for command in re.findall(
                            rb"\\(?:citation|bibdata|bibstyle)\{[^}]*\}",
                            contents,
                        )
                    )
                    if any(
                        cmd.startswith(rb"\bibdata{") for cmd in bib_commands
                    ):
                        bibliography = ("bibtex", bib_commands)
                bibliography_ran = (
                    bibliography is not None
                    and bibliography != bibliography_state
                )
                if bibliography_ran:
                    executable = bibliography[0]
                    if shutil.which(executable) is None:
                        raise SystemExit(
                            f"pd: {executable} is not on PATH; the diff "
                            "TeX has been retained."
                        )
                    stage = (
                        f"running {executable} for {output} "
                        "(the diff TeX has been retained)"
                    )
                    subprocess.run(
                        [executable, output.stem],
                        cwd=output.parent,
                        check=True,
                    )
                    bibliography_state = bibliography
                    stage = (
                        f"compiling {output} "
                        "(the diff TeX has been retained)"
                    )
                state = dict(aux_files)
                for suffix in (".toc", ".out", ".lof", ".lot"):
                    artifact = output.with_suffix(suffix)
                    if artifact.is_file():
                        state[artifact] = artifact.read_bytes()
                log = output.with_suffix(".log")
                rerun_requested = log.is_file() and re.search(
                    r"Rerun to get|Please rerun LaTeX|"
                    r"Please \(re\)run (?:Biber|BibTeX)",
                    log.read_text(encoding="utf-8", errors="replace"),
                )
                if (
                    pass_number > 0
                    and state == previous_state
                    and not bibliography_ran
                    and not rerun_requested
                ):
                    break
                previous_state = state
            else:
                raise SystemExit(
                    "pd: LaTeX references did not settle after six passes; "
                    "the diff TeX and compilation artifacts have been "
                    "retained."
                )
            print(f"PDF diff: {output.with_suffix('.pdf')}")
        # }}}
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"pd: failed while {stage}: {exc}") from None


# also used by: tests/test_git_pdf_diff.py, which checks argument forwarding.
def git_pd(arguments):
    """Let Git select snapshots using its normal diff arguments."""
    # {{{ extract our flag and forward the remaining arguments to Git
    split = arguments.index("--") if "--" in arguments else len(arguments)
    options = arguments[:split]
    no_compile = "--no-compile" in options
    options = [arg for arg in options if arg != "--no-compile"]
    arguments = options + arguments[split:]
    command = [sys.executable, "-m", "pydifftools.pdf_diff", "--git-external"]
    if no_compile:
        command.append("--no-compile")
    env = os.environ.copy()
    # Git shell aliases run at the root and record the caller's subdirectory.
    directory = Path.cwd() / env.pop("GIT_PREFIX", "")
    env["GIT_EXTERNAL_DIFF"] = " ".join(shlex.quote(arg) for arg in command)
    env["GIT_EXTERNAL_DIFF_TRUST_EXIT_CODE"] = "0"
    try:
        result = subprocess.run(
            ["git", "--no-pager", "diff", "--ext-diff", *arguments],
            cwd=directory,
            env=env,
        )
    except OSError as exc:
        raise SystemExit(f"pd: cannot run git diff: {exc}") from None
    if result.returncode:
        raise SystemExit(result.returncode)
    # }}}


# also used by: tests/test_git_pdf_diff.py, which checks Git snapshot handling.
def git_external_diff(arguments):
    """Handle Git's external-diff protocol, including renamed paths."""
    no_compile = arguments[:1] == ["--no-compile"]
    if no_compile:
        arguments = arguments[1:]
    if len(arguments) == 1:
        raise SystemExit(
            f"pd: resolve merge conflicts in {arguments[0]} first"
        )
    if len(arguments) not in (7, 9):
        raise SystemExit("pd: invalid Git external-diff arguments")
    old_path = Path(arguments[0])
    new_path = Path(arguments[7]) if len(arguments) == 9 else old_path
    if new_path.suffix.lower() not in {".md", ".tex"}:
        print(f"pd: skipping unsupported document: {new_path}")
        return
    if old_path.suffix.lower() != new_path.suffix.lower():
        raise SystemExit("pd: renamed documents must keep the same extension")
    # {{{ materialize snapshots while keeping outputs and resources local
    try:
        root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        output = root / new_path.with_name(new_path.stem + "_diff.tex")
        output.parent.mkdir(parents=True, exist_ok=True)
        old_directory = (root / old_path).parent
        if not old_directory.is_dir():
            old_directory = output.parent
        with tempfile.TemporaryDirectory(prefix="pydifft-git-pd-") as temp:
            snapshots = []
            for label, filename in zip(
                ("old", "new"),
                (arguments[1], arguments[4]),
            ):
                snapshot = Path(temp) / (label + new_path.suffix)
                contents = (
                    b""
                    if filename == "/dev/null"
                    else Path(filename).read_bytes()
                )
                snapshot.write_bytes(contents)
                snapshots.append(snapshot)
            render_pdf_diff(
                *snapshots,
                no_compile=no_compile,
                output=output,
                source_dirs=(old_directory, output.parent),
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"pd: cannot read Git comparison: {exc}") from None
    # }}}


if __name__ == "__main__":
    if sys.argv[1:2] != ["--git-external"]:
        raise SystemExit("Use pydifft pd --help for usage.")
    git_external_diff(sys.argv[2:])
