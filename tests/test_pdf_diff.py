"""PDF diff behavior, failure preservation, and real tool integration."""

from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image
import pytest

from pydifftools import command_line, pdf_diff


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old_dir = tmp_path / "old project"
    new_dir = tmp_path / "new project"
    old_dir.mkdir()
    new_dir.mkdir()
    old = old_dir / "old version.tex"
    new = new_dir / "new version.tex"
    old.write_text("old source\n")
    new.write_text("new source\n")
    preamble = tmp_path / "mylatexdiff-preamble.sty"
    preamble.write_text("custom preamble\n")
    return old, new, preamble


@pytest.fixture
def tools_stub(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf_diff.shutil, "which", lambda name: name)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "pandoc":
            Path(command[command.index("--output") + 1]).write_text(
                "converted source\n"
                r"\@ifpackageloaded{subfig}{}{\usepackage{subfig}}"
                "\n"
                r"\captionsetup[subfloat]{margin=0.5em}"
                "\n"
            )
        return subprocess.CompletedProcess(command, 0, stdout=b"diff\n")

    monkeypatch.setattr(pdf_diff.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("flag_first", [True, False])
def test_cli_flag_placement_and_help(project, monkeypatch, capsys, flag_first):
    old, new, _ = project
    calls = []
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    monkeypatch.setitem(
        command_line._COMMAND_SPECS["pd"],
        "handler",
        lambda **kwargs: calls.append(kwargs),
    )
    args = [str(old), str(new)]
    args.insert(0 if flag_first else len(args), "--no-compile")
    command_line.main(["pd", *args])
    assert calls == [{"old": str(old), "new": str(new), "no_compile": True}]
    command_line.main(["--help", "pd"])
    help_text = capsys.readouterr().out
    assert "OLD NEW" in help_text
    assert "--no-compile" in help_text
    spec = command_line._COMMAND_SPECS["pd"]["arguments"][0]
    assert spec["completion_allowednames"] == ["*.md", "*.tex"]


@pytest.mark.parametrize(
    "old_name,new_name,message",
    [
        ("old.txt", "new.txt", ".md or .tex"),
        ("old.md", "new.tex", "same extension"),
        ("missing.tex", "new.tex", "does not exist"),
        ("new_diff.tex", "new.tex", "overwrite an input"),
    ],
)
def test_invalid_inputs(tmp_path, monkeypatch, old_name, new_name, message):
    monkeypatch.chdir(tmp_path)
    for name in (old_name, new_name):
        if not name.startswith("missing"):
            (tmp_path / name).write_text("source")
    with pytest.raises(SystemExit, match=message):
        pdf_diff.pd(old_name, new_name, no_compile=True)


def test_tex_no_compile_and_legacy_postprocessing(project, monkeypatch):
    old, new, preamble = project
    original = old.read_bytes(), new.read_bytes()
    raw = (
        b"%DIF > REMOVE first %DIF > REMOVE second\r\n"
        b"%REMOVE first %REMOVE second\r\n"
        rb"\john[\DIFadd{one}]{text} \john[\DIFdel{two}]{text}"
        b"\r\n"
    )
    monkeypatch.setattr(pdf_diff.shutil, "which", lambda name: name)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=raw)

    monkeypatch.setattr(pdf_diff.subprocess, "run", run)
    pdf_diff.pd(str(old), str(new), no_compile=True)
    output = new.with_name("new version_diff.tex")
    assert output.read_bytes() == (
        b"first %DIF > REMOVE second\nfirst %REMOVE second\n"
        rb"\john[\protect\DIFadd{one}]{text} \john[\DIFdel{two}]{text}"
        b"\n"
    )
    assert len(calls) == 1
    command = calls[0]
    assert command[:3] == ["latexdiff", "-p", str(preamble)]
    assert command[-2:] == [str(old), str(new)]
    assert command[command.index("--exclude-textcmd") + 1] == "john,bibcite"
    assert command[command.index("--exclude-safecmd") + 1] == "bibcite"
    assert (old.read_bytes(), new.read_bytes()) == original
    assert not output.with_suffix(".pdf").exists()
    assert not list(new.parent.glob(".pydifft-pd-*"))


@pytest.mark.parametrize("location", ["current", "new", "tex-tree"])
def test_preamble_search_order(project, tools_stub, monkeypatch, location):
    old, new, current = project
    adjacent = new.parent / current.name
    adjacent.write_text("adjacent preamble")
    tree = old.parent / current.name
    tree.write_text("tree preamble")
    if location != "current":
        current.unlink()
    if location == "tex-tree":
        adjacent.unlink()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "kpsewhich":
            return subprocess.CompletedProcess(command, 0, str(tree) + "\n")
        return subprocess.CompletedProcess(command, 0, b"diff\n")

    monkeypatch.setattr(pdf_diff.subprocess, "run", run)
    pdf_diff.pd(str(old), str(new), no_compile=True)
    expected = {"current": current, "new": adjacent, "tex-tree": tree}
    assert calls[-1][2] == str(expected[location])
    assert (calls[0][0] == "kpsewhich") == (location == "tex-tree")


def test_missing_preamble_and_tools(project, monkeypatch):
    old, new, preamble = project
    monkeypatch.setattr(pdf_diff.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="latexdiff is not on PATH"):
        pdf_diff.pd(str(old), str(new), no_compile=True)
    preamble.unlink()
    monkeypatch.setattr(
        pdf_diff.shutil,
        "which",
        lambda name: None if name == "kpsewhich" else name,
    )
    with pytest.raises(SystemExit, match="cannot find.*preamble"):
        pdf_diff.pd(str(old), str(new), no_compile=True)


@pytest.mark.parametrize("no_compile", [True, False])
def test_markdown_conversion_and_cleanup(project, tools_stub, no_compile):
    old, new, _ = project
    old = old.rename(old.with_suffix(".md"))
    new = new.rename(new.with_suffix(".md"))
    original = old.read_bytes(), new.read_bytes()
    pdf_diff.pd(str(old), str(new), no_compile=no_compile)
    conversions = [(cmd, kw) for cmd, kw in tools_stub if cmd[0] == "pandoc"]
    assert len(conversions) == 2
    for (cmd, kwargs), source in zip(conversions, (old, new)):
        assert kwargs["cwd"] == source.parent
        assert kwargs["check"]
        assert "--standalone" in cmd
        assert "--citeproc" in cmd
        assert "--filter=pandoc-crossref" in cmd
        assert not Path(cmd[cmd.index("--output") + 1]).exists()
        assert not Path(cmd[cmd.index("--lua-filter") + 1]).exists()
    diff_cmd = next(cmd for cmd, _ in tools_stub if cmd[0] == "latexdiff")
    assert all(not Path(name).exists() for name in diff_cmd[-2:])
    assert (old.read_bytes(), new.read_bytes()) == original
    assert new.with_name("new version_diff.tex").read_text() == "diff\n"
    assert list(old.parent.iterdir()) == [old]
    compile_calls = [
        (cmd, kw) for cmd, kw in tools_stub if cmd[0] == "latexmk"
    ]
    assert len(compile_calls) == (0 if no_compile else 1)
    if not no_compile:
        cmd, kwargs = compile_calls[0]
        assert cmd[-1] == "new version_diff.tex"
        assert "-pdf" in cmd
        assert "-halt-on-error" in cmd
        assert kwargs["cwd"] == new.parent


@pytest.mark.parametrize("failed_tool", ["pandoc", "latexdiff", "latexmk"])
def test_failure_preserves_output(
    project, tools_stub, monkeypatch, failed_tool
):
    old, new, _ = project
    if failed_tool == "pandoc":
        old = old.rename(old.with_suffix(".md"))
        new = new.rename(new.with_suffix(".md"))
    output = new.with_name("new version_diff.tex")
    output.write_text("previous successful diff")
    stub = pdf_diff.subprocess.run

    def run(command, **kwargs):
        if command[0] == failed_tool:
            raise subprocess.CalledProcessError(1, command)
        return stub(command, **kwargs)

    monkeypatch.setattr(pdf_diff.subprocess, "run", run)
    with pytest.raises(SystemExit, match="failed while") as exc:
        pdf_diff.pd(str(old), str(new))
    if failed_tool == "latexmk":
        assert output.read_text() == "diff\n"
        assert "retained" in str(exc.value)
    else:
        assert output.read_text() == "previous successful diff"
    assert not list(new.parent.glob(".pydifft-pd-*"))


@pytest.mark.parametrize("extension", [".md", ".tex"])
def test_real_pdf_diff(tmp_path, monkeypatch, extension):
    required = ["latexdiff", "latexmk", "pdflatex"]
    if extension == ".md":
        required += ["pandoc", "pandoc-crossref"]
    if not all(shutil.which(name) for name in required):
        pytest.skip("real PDF tools are not on PATH")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mylatexdiff-preamble.sty").write_text(
        r"\usepackage{xcolor}"
        "\n"
        r"\providecommand{\DIFadd}[1]{\textcolor{blue}{#1}}"
        "\n"
        r"\providecommand{\DIFdel}[1]{\textcolor{red}{#1}}"
        "\n"
        r"\providecommand{\DIFaddbegin}{}"
        "\n"
        r"\providecommand{\DIFaddend}{}"
        "\n"
        r"\providecommand{\DIFdelbegin}{}"
        "\n"
        r"\providecommand{\DIFdelend}{}"
        "\n"
        r"\providecommand{\DIFaddFL}[1]{\DIFadd{#1}}"
        "\n"
        r"\providecommand{\DIFdelFL}[1]{\DIFdel{#1}}"
        "\n"
        r"\providecommand{\DIFaddbeginFL}{}"
        "\n"
        r"\providecommand{\DIFaddendFL}{}"
        "\n"
        r"\providecommand{\DIFdelbeginFL}{}"
        "\n"
        r"\providecommand{\DIFdelendFL}{}"
        "\n"
    )
    old_dir, new_dir = tmp_path / "old project", tmp_path / "new project"
    old_dir.mkdir()
    new_dir.mkdir()
    old, new = old_dir / ("old" + extension), new_dir / ("new" + extension)
    if extension == ".md":
        for directory in (old_dir, new_dir):
            Image.new("RGB", (20, 10), "blue").save(directory / "figure.png")
            (directory / "refs.bib").write_text(
                "@book{sample, author={Jane Doe}, "
                "title={Example}, year={2020}}"
            )
        content = (
            "---\nbibliography: refs.bib\n---\n\n# Results\n\n"
            "The original result has $x=1$. See [@sample].\n\n"
            "![Example.](figure.png){#fig:example width=10mm}\n\n"
            "See @fig:example.\n\n$$y=x^2$${#eq:example}\n\n"
            "See @eq:example.\n"
        )
    else:
        content = (
            r"\documentclass{article}"
            "\n"
            r"\begin{document}"
            "\n"
            "The original result has $x=1$.\n"
            r"\end{document}"
            "\n"
        )
    old.write_text(content)
    new.write_text(content.replace("original", "revised"))
    original = old.read_bytes(), new.read_bytes()
    pdf_diff.pd(str(old), str(new))
    output = new_dir / "new_diff.tex"
    assert output.with_suffix(".pdf").read_bytes().startswith(b"%PDF-")
    tex = output.read_text()
    assert r"\DIFadd" in tex and r"\DIFdel" in tex
    assert (old.read_bytes(), new.read_bytes()) == original
    if extension == ".md":
        assert str(old_dir / "figure.png") in tex
        assert str(new_dir / "figure.png") in tex
        assert "Doe" in tex and "2020" in tex
        assert r"\ref{fig:example}" in tex
        assert r"\ref{eq:example}" in tex
        assert not list(old_dir.glob("*.tex"))
        assert list(new_dir.glob("*.tex")) == [output]
