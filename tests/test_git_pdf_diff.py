"""Git alias installation and Git-selected document snapshots."""

import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from pydifftools import command_line, pdf_diff
from pydifftools.git_aliases import install_git_alias


@pytest.fixture
def git_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_PREFIX", raising=False)
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.name", "Test Author"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        check=True,
    )
    source = tmp_path / "documents" / "paper with spaces.md"
    source.parent.mkdir()
    source.write_text("# Results\n\nThe original result.\n")
    subprocess.run(["git", "add", "documents"], check=True)
    subprocess.run(["git", "commit", "-qm", "Baseline"], check=True)
    # A project preamble keeps the integration test independent of user files.
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
    )
    return source


def test_pd_installs_alias_without_document_arguments(git_project, capsys):
    command_line.main(["--add_to_git", "pd"])
    alias = subprocess.run(
        ["git", "config", "--global", "--get", "alias.pd"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")
    assert alias == '!f() { pydifft pd --git "$@"; }; f'
    assert "alias.pd" in capsys.readouterr().out
    command_line.main(["--add_to_git", "pd"])
    assert subprocess.run(
        ["git", "config", "--global", "--get-all", "alias.pd"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines() == [alias]


def test_gd_preserves_exact_existing_command(git_project):
    custom = '!f() { printf "custom gd\\n"; pydifft gd "$@"; }; f  '
    subprocess.run(
        ["git", "config", "--global", "alias.gd", custom],
        check=True,
    )
    subprocess.run(
        ["git", "config", "--global", "other.setting", "retain this"],
        check=True,
    )
    command_line.main(["--add_to_git", "gd"])
    assert (
        subprocess.run(
            ["git", "config", "--global", "--null", "--get", "alias.gd"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == custom + "\0"
    )
    assert (
        subprocess.run(
            ["git", "config", "--global", "--get", "other.setting"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == "retain this\n"
    )


def test_gd_installs_current_default_when_missing(git_project, capsys):
    command_line.main(["--add_to_git", "gd"])
    assert (
        subprocess.run(
            ["git", "config", "--global", "--get", "alias.gd"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.rstrip("\n")
        == '!f() { pydifft gd "$@"; }; f'
    )
    assert "alias.gd" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        ["--add_to_git", "pd", "old.md"],
        ["--add_to_git", "pd", "--no-compile"],
        ["--add_to_git", "gd", "HEAD"],
        ["pd"],
        ["pd", "old.md"],
    ],
)
def test_invalid_install_and_file_arguments(git_project, args):
    with pytest.raises(SystemExit):
        command_line.main(args)
    assert not Path(os.environ["GIT_CONFIG_GLOBAL"]).exists()


def test_installer_reports_failed_config_read(monkeypatch):
    monkeypatch.setattr(
        "pydifftools.git_aliases.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            3,
            stdout="",
            stderr="malformed configuration",
        ),
    )
    with pytest.raises(SystemExit, match="Cannot read.*malformed"):
        install_git_alias("gd", "default", preserve_existing=True)


def test_git_mode_forwards_diff_args_and_restores_prefix(
    git_project,
    monkeypatch,
):
    calls = []
    monkeypatch.setenv("GIT_PREFIX", "documents/")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pdf_diff.subprocess, "run", run)
    command_line.main(
        [
            "pd",
            "--git",
            "--cached",
            "--no-compile",
            "HEAD",
            "--",
            "paper with spaces.md",
        ]
    )
    command, kwargs = calls[0]
    assert command == [
        "git",
        "--no-pager",
        "diff",
        "--ext-diff",
        "--cached",
        "HEAD",
        "--",
        "paper with spaces.md",
    ]
    assert kwargs["cwd"] == git_project.parent
    assert "GIT_PREFIX" not in kwargs["env"]
    assert "--git-external --no-compile" in kwargs["env"]["GIT_EXTERNAL_DIFF"]


@pytest.mark.parametrize("exit_code", [1, 128])
def test_git_mode_preserves_git_exit_code(git_project, monkeypatch, exit_code):
    monkeypatch.setattr(
        pdf_diff.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            exit_code,
        ),
    )
    with pytest.raises(SystemExit) as exc:
        pdf_diff.git_pd(["--exit-code", "--", "documents"])
    assert exc.value.code == exit_code


@pytest.mark.parametrize("kind", ["modified", "added", "deleted", "renamed"])
def test_external_diff_snapshots_and_output(git_project, monkeypatch, kind):
    old = git_project.parent / "old blob"
    new = git_project.parent / "new blob"
    old.write_text("original snapshot")
    new.write_text("revised snapshot")
    source_path = git_project.relative_to(Path.cwd()).as_posix()
    args = [
        source_path,
        str(old),
        "a" * 40,
        "100644",
        str(new),
        "b" * 40,
        "100644",
    ]
    if kind == "added":
        args[1] = "/dev/null"
    elif kind == "deleted":
        args[4] = "/dev/null"
    elif kind == "renamed":
        args += ["documents/renamed.md", "similarity index 80%"]
    snapshots = []

    def render(old, new, **kwargs):
        snapshots.extend([old, new])
        assert old.read_text() == (
            "" if kind == "added" else "original snapshot"
        )
        assert new.read_text() == (
            "" if kind == "deleted" else "revised snapshot"
        )
        assert old.suffix == new.suffix == ".md"
        assert kwargs["no_compile"]
        assert kwargs["source_dirs"] == (
            git_project.parent,
            git_project.parent,
        )
        output = kwargs["output"]
        expected = (
            "renamed_diff.tex"
            if kind == "renamed"
            else "paper with spaces_diff.tex"
        )
        assert output == git_project.parent / expected
        output.write_text("diff retained")

    monkeypatch.setattr(pdf_diff, "render_pdf_diff", render)
    pdf_diff.git_external_diff(["--no-compile", *args])
    assert all(not path.exists() for path in snapshots)
    assert git_project.read_text().startswith("# Results")


def test_external_diff_skips_other_types_and_rejects_conflicts(capsys):
    pdf_diff.git_external_diff(["code.py", "", "", "", "", "", ""])
    assert "skipping" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="resolve merge conflicts"):
        pdf_diff.git_external_diff(["paper.md"])


@pytest.mark.parametrize("mode", ["unstaged", "revision", "cached", "range"])
def test_real_git_alias_pdf(git_project, monkeypatch, mode):
    if not all(
        shutil.which(name)
        for name in (
            "pandoc",
            "pandoc-crossref",
            "latexdiff",
            "pdflatex",
        )
    ):
        pytest.skip("real PDF tools are not on PATH")
    command_line.main(["--add_to_git", "pd"])
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git_project.write_text("# Results\n\nThe revised result.\n")
    options = []
    if mode == "revision":
        options = [baseline[:7]]
    elif mode in {"cached", "range"}:
        subprocess.run(["git", "add", "documents"], check=True)
        if mode == "cached":
            options = ["--cached"]
        else:
            subprocess.run(["git", "commit", "-qm", "Revision"], check=True)
            options = [baseline + "..HEAD"]
        git_project.write_text("# Results\n\nAn unrelated working edit.\n")
    before = git_project.read_bytes()
    # Test the real alias from a subdirectory, including path quoting.
    subprocess.run(
        ["git", "pd", *options, "--", git_project.name],
        cwd=git_project.parent,
        check=True,
    )
    output = git_project.with_name("paper with spaces_diff.tex")
    assert output.with_suffix(".pdf").read_bytes().startswith(b"%PDF-")
    tex = output.read_text()
    assert "original" in tex and "revised" in tex
    assert "unrelated" not in tex
    assert git_project.read_bytes() == before


@pytest.mark.parametrize("extension", [".md", ".tex"])
@pytest.mark.parametrize("kind", ["added", "deleted", "renamed"])
def test_real_git_add_delete_rename(git_project, extension, kind):
    if not all(
        shutil.which(name)
        for name in (
            "pandoc",
            "pandoc-crossref",
            "latexdiff",
            "pdflatex",
        )
    ):
        pytest.skip("real PDF tools are not on PATH")
    source = git_project.with_suffix(extension)
    if extension == ".md":
        (source.parent / "refs.bib").write_text(
            "@book{sample, author={Jane Doe}, title={Example}, year={2020}}"
        )
        content = (
            "---\nbibliography: refs.bib\n---\n\n"
            "# Results\n\nThe original result cites [@sample].\n\n"
            + "A paragraph of unchanged context.\n\n" * 10
        )
    else:
        content = (
            r"\documentclass{article}"
            "\n"
            r"\begin{document}"
            "\n"
            "The original result.\n\n"
            + "A paragraph of unchanged context.\n\n" * 10
            + r"\end{document}"
            "\n"
        )
    source.write_text(content)
    subprocess.run(["git", "add", "documents"], check=True)
    subprocess.run(["git", "commit", "-qm", "Document"], check=True)
    command_line.main(["--add_to_git", "pd"])
    if kind == "added":
        source = source.with_name("added" + extension)
        source.write_text(content)
        subprocess.run(["git", "add", "documents"], check=True)
    elif kind == "deleted":
        source.unlink()
        subprocess.run(["git", "add", "documents"], check=True)
    else:
        renamed = source.with_name("renamed" + extension)
        subprocess.run(["git", "mv", str(source), str(renamed)], check=True)
        source = renamed
        source.write_text(content.replace("original", "revised"))
        subprocess.run(["git", "add", "documents"], check=True)
    before = source.read_bytes() if source.exists() else None
    # Git needs both sides in the pathspec to detect a rename.
    selected = source.parent if kind == "renamed" else source
    subprocess.run(
        [
            "git",
            "pd",
            "--cached",
            "--find-renames",
            "--",
            selected.relative_to(Path.cwd()).as_posix(),
        ],
        check=True,
    )
    output = source.with_name(source.stem + "_diff.tex")
    assert output.with_suffix(".pdf").read_bytes().startswith(b"%PDF-")
    tex = output.read_text()
    assert "original" in tex
    if kind == "renamed":
        assert "revised" in tex
    if kind == "deleted":
        assert not source.exists()
    else:
        assert source.read_bytes() == before


def test_real_git_no_compile_and_unchanged_file(git_project):
    if not all(
        shutil.which(name)
        for name in (
            "pandoc",
            "pandoc-crossref",
            "latexdiff",
        )
    ):
        pytest.skip("real PDF diff tools are not on PATH")
    command_line.main(["--add_to_git", "pd"])
    subprocess.run(
        [
            "git",
            "pd",
            "--no-compile",
            "--",
            str(git_project),
        ],
        check=True,
    )
    output = git_project.with_name(git_project.stem + "_diff.tex")
    assert not output.exists()
    git_project.write_text("# Results\n\nThe revised result.\n")
    subprocess.run(
        [
            "git",
            "pd",
            "--no-compile",
            "HEAD",
            "--",
            str(git_project),
        ],
        check=True,
    )
    assert output.exists()
    assert not output.with_suffix(".pdf").exists()
