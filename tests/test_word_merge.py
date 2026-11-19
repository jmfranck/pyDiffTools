"""Word-wise conflict merging, gvim panes, and git mergetool install."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from pydifftools import command_line
from pydifftools.word_merge import conflict_views, merge_texts

FIXTURES = Path(__file__).parent / "fixtures" / "wmerge"


@pytest.mark.parametrize("base, local, remote, expected", [
    (
        "Hello my name is John\n",
        "Hello my name is definitely John\n",
        "Hello my name is Bob\n",
        "Hello my name is definitely Bob\n",
    ),
    (
        "Hello my name is John\n",
        "Hello my name is Mark\n",
        "Hello my name is Philip\n",
        "Hello my name is [-John][L+Mark][R+Philip]\n",
    ),
    (
        "Hello my name is John\n",
        "Hello my name is John Smith\n",
        "Hello my name is Bob\n",
        "Hello my name is Bob Smith\n",
    ),
    (
        "Hello my name is John\n",
        "Hello my name is Bob\n",
        "Hello my name is Bob\n",
        "Hello my name is Bob\n",
    ),
    ("one two\nthree four\n", "one 2\nthree four\n",
     "one two\nthree 4\n", "one 2\nthree 4\n"),
    # brackets with too few unchanged words between them are joined
    (
        "a b c d e f g\n",
        "a L1 c L2 e L3 g\n",
        "a R1 c R2 e R3 g\n",
        "a [-b c d e f][L+L1 c L2 e L3][R+R1 c R2 e R3] g\n",
    ),
    # line breaks that matter (around headers) survive word merging
    (
        "# A\n\ntext one two\n",
        "# A\n\ntext one three\n",
        "# B\n\ntext one two\n",
        "# B\n\ntext one three\n",
    ),
    # a rewrapped line keeps the new line breaks
    (
        "one two three four\nfive six\n",
        "one two\nthree four five six\n",
        "one two three four\nfive seven\n",
        "one two\nthree four five seven\n",
    ),
])
def test_merge_texts(base, local, remote, expected):
    assert merge_texts(base, local, remote) == expected


def test_multiline_bracket_parts_start_on_new_lines():
    assert merge_texts(
        "keep this\nalpha beta\ngamma delta\nkeep that\n",
        "keep this\nepsilon zeta\neta theta\nkeep that\n",
        "keep this\niota kappa\nlambda mu\nkeep that\n",
    ) == (
        "keep this\n[-alpha beta\ngamma delta]\n"
        "[L+epsilon zeta\neta theta]\n"
        "[R+iota kappa\nlambda mu]\nkeep that\n"
    )


def test_edited_move_carries_both_sides_edits():
    base = (
        "# Top\n\nIntro words stay here.\n\n"
        "The moved paragraph has quite a few words in it.\n\n"
        "# End\n\nClosing words stay too.\n"
    )
    local = (
        "# Top\n\nIntro words stay here.\n\n"
        "# End\n\nClosing words stay too.\n\n"
        "The moved paragraph has quite many words in it.\n"
    )
    remote = base.replace("a few words", "a few nice words")
    # the source keeps only a numbered tag; the target holds the text
    assert merge_texts(base, local, remote) == (
        "# Top\n\nIntro words stay here.\n\n"
        "[L →m00]\n\n"
        "# End\n\nClosing words stay too.\n\n"
        "[L m00→ The moved paragraph has quite"
        " [-a few][L+many][R+a few nice] words in it.]\n"
    )


def test_light_edits_shown_inline_against_a_rewrite():
    base = ("Start here. alpha beta gamma delta epsilon zeta eta theta"
            " iota kappa. End here.\n")
    local = base.replace("delta", "DELTA")
    remote = ("Start here. completely new words replace that whole"
              " sentence now. End here.\n")
    assert merge_texts(base, local, remote) == (
        "Start here. [R-alpha beta gamma [L-delta][L+DELTA] epsilon zeta"
        " eta theta iota kappa.][R+completely new words replace that"
        " whole sentence now.] End here.\n"
    )


def test_unedited_move_is_silent():
    base = (
        "# Top\n\nIntro words stay here.\n\n"
        "The moved paragraph has quite a few words in it.\n\n"
        "# End\n\nClosing words stay too.\n"
    )
    local = (
        "# Top\n\nIntro words stay here.\n\n"
        "# End\n\nClosing words stay too.\n\n"
        "The moved paragraph has quite a few words in it.\n"
    )
    remote = base.replace("Closing words", "Final words")
    assert merge_texts(base, local, remote) == local.replace(
        "Closing words", "Final words"
    )


def test_bracketed_parts_keep_brackets_balanced():
    # a clash inside a citation is widened to the whole citation, so no
    # merge bracket holds a lone "]"
    assert merge_texts(
        "see [@Van; @Bai; @Sim] here.\n",
        "see [@Van; @Bai; @Sims] here.\n",
        "see [@Van; @Bai; @Simo] here.\n",
    ) == (
        "see [-[@Van; @Bai; @Sim]][L+[@Van; @Bai; @Sims]]"
        "[R+[@Van; @Bai; @Simo]] here.\n"
    )


def test_clashing_insertions_at_line_end_stay_on_the_line():
    assert merge_texts(
        "Low as 243 K.\nNext line.\n",
        "Low as 243 K. More.\nNext line.\n",
        "Low as 243 K. Less.\nNext line.\n",
    ) == "Low as 243 K. [L+More.][R+Less.]\nNext line.\n"


def test_recorded_conflict():
    """A real manuscript conflict: local moved several (edited) passages
    into and out of conflicted regions while remote edited them in
    place; see proposed representation agreed for wmerge."""
    def read(name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    assert merge_texts(
        read("base.md"), read("local.md"), read("remote.md"),
        merged=read("merged.md"),
    ) == read("expected.md")


def test_conflict_views():
    draft, spans = conflict_views(
        "top\n<<<<<<< HEAD\nlocal\n||||||| base\nbase text\n"
        "=======\nremote\n>>>>>>> other\nbottom\n"
    )
    assert draft == "top\nbase text\nbottom\n"
    assert [draft[a:b] for a, b in spans] == ["base text\n"]


def test_merge_style_conflict_explains_diff3():
    with pytest.raises(ValueError, match="merge.conflictstyle diff3"):
        conflict_views("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> other\n")


def git(*args):
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def conflicted_repo(tmp_path, monkeypatch):
    """A repository with a diff3 conflict and a scripted stand-in gvim."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # {{{ gvim -d -f -S SCRIPT DRAFT MERGED: copy MERGED over DRAFT when
    #     WMERGE_TEST_EDIT is set, after checking the dS mapping script
    gvim = bin_dir / "gvim"
    gvim.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:3] == ['-d', '-f', '-S'], args\n"
        "script = open(args[3], encoding='utf-8').read()\n"
        "assert 'dS' in script and '<buffer>' in script\n"
        "if os.environ.get('WMERGE_TEST_SCRIPT'):\n"
        "    import shutil\n"
        "    shutil.copy(args[3], os.environ['WMERGE_TEST_SCRIPT'])\n"
        "if os.environ.get('WMERGE_TEST_EDIT'):\n"
        "    text = open(args[5], encoding='utf-8').read()\n"
        "    open(args[4], 'w', encoding='utf-8').write(text)\n"
    )
    gvim.chmod(0o755)
    # }}}
    launcher = bin_dir / "pydifft"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "from pydifftools.command_line import main\nmain()\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    git("init", "--initial-branch=main")
    git("config", "user.name", "Test Author")
    git("config", "user.email", "test@example.invalid")
    git("config", "merge.conflictstyle", "diff3")
    Path("story.md").write_text("Hello my name is John\n")
    git("add", "story.md")
    git("commit", "-m", "base")
    git("checkout", "-b", "other")
    Path("story.md").write_text("Hello my name is Bob\n")
    git("commit", "-am", "remote")
    git("checkout", "main")
    Path("story.md").write_text("Hello my name is definitely John\n")
    git("commit", "-am", "local")
    assert subprocess.run(["git", "merge", "other"],
                          capture_output=True).returncode
    return work


def test_wmerge_resolves_and_stages_edited_draft(
    conflicted_repo, monkeypatch,
):
    monkeypatch.setenv("WMERGE_TEST_EDIT", "1")
    command_line.main(["wmerge"])
    assert Path("story.md").read_text() == "Hello my name is definitely Bob\n"
    assert git("status", "--short") == "M  story.md"


def test_wmerge_unchanged_draft_stays_conflicted(conflicted_repo):
    before = Path("story.md").read_text()
    with pytest.raises(SystemExit) as exc:
        command_line.main(["wmerge", "story.md"])
    assert exc.value.code == 1
    assert Path("story.md").read_text() == before
    assert git("status", "--short") == "UU story.md"


def test_installed_mergetool(conflicted_repo, monkeypatch, capsys):
    command_line.main(["--add_to_git", "wmerge"])
    assert git(
        "config", "--global", "--get", "mergetool.pydifft.cmd"
    ) == 'pydifft wmerge "$MERGED"'
    assert git("config", "--global", "--get", "alias.wmerge")
    assert "git mergetool -t pydifft" in capsys.readouterr().out
    monkeypatch.setenv("WMERGE_TEST_EDIT", "1")
    git("mergetool", "--no-prompt", "-t", "pydifft")
    assert Path("story.md").read_text() == "Hello my name is definitely Bob\n"
    assert git("status", "--short", "--", "story.md") == "M  story.md"


def test_install_sets_diff3_only_when_needed(conflicted_repo):
    git("config", "--global", "merge.conflictstyle", "zdiff3")
    command_line.main(["--add_to_git", "wmerge"])
    assert git(
        "config", "--global", "--get", "merge.conflictstyle"
    ) == "zdiff3"
    git("config", "--global", "--unset", "merge.conflictstyle")
    command_line.main(["--add_to_git", "wmerge"])
    assert git(
        "config", "--global", "--get", "merge.conflictstyle"
    ) == "diff3"


@pytest.mark.skipif(shutil.which("vim") is None, reason="needs vim")
def test_gvim_script_marks_and_dS(conflicted_repo, monkeypatch, tmp_path):
    script = tmp_path / "wmerge.vim"
    monkeypatch.setenv("WMERGE_TEST_SCRIPT", str(script))
    with pytest.raises(SystemExit):
        command_line.main(["wmerge", "story.md"])
    other = tmp_path / "other.md"
    other.write_text("x\n")

    def vim(text, *commands):
        target = tmp_path / "t.md"
        target.write_text(text, encoding="utf-8")
        subprocess.run(
            ["vim", "-N", "-u", "NONE", "-i", "NONE", "-Es", "-d",
             str(target), str(other), "-S", str(script),
             *[a for c in commands for a in ("-c", c)],
             "-c", "1wincmd w", "-c", "w", "-c", "qa!"],
            check=True, timeout=30,
        )
        return target.read_text(encoding="utf-8")

    # dS finds the matching "]" past quotes and nested brackets, skips
    # brackets that do not enclose the cursor, and drops the tag
    for text, column, expected in [
        ('(was [R-"SW!][R+"SW:] as" before)\n', 7,
         '(was "SW![R+"SW:] as" before)\n'),
        ("x [L+see (a [b] c)] y\n", 4, "x see (a [b] c) y\n"),
        ("x [L m0f→ moved [L-John][L+Bob] text] y\n", 36,
         "x moved [L-John][L+Bob] text y\n"),
        ("y [R →m0a] z\n", 4, "y  z\n"),
    ]:
        assert vim(text, f"call cursor(1, {column})", "normal dS") \
            == expected
    # each tag and its matching "]" are highlighted
    marks = tmp_path / "marks.txt"
    vim(
        'a [L m00→ x [R-"q] y\n(z)] [-p [q] r]\n',
        "call writefile(map(getmatches(), "
        f"'string([v:val.pos1, v:val.pos2])'), '{marks}')",
    )
    assert marks.read_text().split("\n")[:3] == [
        "[[1, 3, 10], [2, 4, 1]]",
        "[[1, 15, 3], [1, 20, 1]]",
        "[[2, 6, 2], [2, 15, 1]]",
    ]
