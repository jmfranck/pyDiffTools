import time
import importlib.metadata

import pytest
from selenium.common.exceptions import SessionNotCreatedException

from pydifftools import command_line


@pytest.fixture(autouse=True)
def _skip_update_check(monkeypatch):
    monkeypatch.setenv(
        "PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE",
        time.strftime("%Y-%m-%d", time.gmtime()),
    )


def test_root_help_mentions_subcommand_help_hint(capsys):
    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "***" in out
    assert "--help <subcommand>" in out


@pytest.mark.parametrize("flag", ["--ver", "--version"])
def test_version_flag_prints_current_version_without_update_check(
    monkeypatch, capsys, flag
):
    monkeypatch.setattr(
        command_line.update_check,
        "check_update",
        lambda *_args, **_kwargs: pytest.fail("unexpected update check"),
    )
    with pytest.raises(SystemExit) as excinfo:
        command_line.main([flag])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == importlib.metadata.version(
        "pyDiffTools"
    )


def test_help_then_subcommand_shows_subcommand_options(capsys):
    command_line.main(["--help", "cpb"])
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "cpb" in out
    assert "--comments-to-margin" in out
    assert "--no-comments" in out


def test_short_and_long_help_are_interchangeable_for_subcommand_help(capsys):
    command_line.main(["-h", "cpb"])
    short_out = capsys.readouterr().out
    command_line.main(["--help", "cpb"])
    long_out = capsys.readouterr().out
    assert "--comments-to-margin" in short_out
    assert "--comments-to-margin" in long_out
    assert "--no-comments" in short_out
    assert "--no-comments" in long_out


def test_cpb_rejects_conflicting_comment_flags(capsys):
    with pytest.raises(SystemExit) as excinfo:
        command_line.main(
            ["cpb", "--no-comments", "--comments-to-margin", "notes.md"]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "argument --no-comments" in err
    assert "--comments-to-margin" in err


def test_qmdb_rejects_conflicting_code_flags(capsys):
    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["qmdb", "--always-code", "--no-code"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "argument --no-code" in err
    assert "--always-code" in err


def test_chromedriver_mismatch_has_concise_upgrade_guidance(
    monkeypatch, capsys
):
    def fail_to_start_chrome(**_kwargs):
        raise SessionNotCreatedException(
            "session not created: This version of ChromeDriver only "
            "supports Chrome version 149\n"
            "Current browser version is 148.0.7778.215 with binary path "
            "/usr/bin/google-chrome"
        )

    monkeypatch.setitem(
        command_line._COMMAND_SPECS["cpb"],
        "handler",
        fail_to_start_chrome,
    )
    monkeypatch.setattr(
        command_line.shutil,
        "which",
        lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
    )

    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["cpb", "notes.md"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "ChromeDriver 149 and Chrome 148 do not match" in err
    assert "sudo apt update" in err
    assert (
        "sudo apt install --only-upgrade google-chrome-stable" in err
    )
    assert "Traceback" not in err


def test_other_chrome_session_errors_are_not_hidden(monkeypatch):
    def fail_to_start_chrome(**_kwargs):
        raise SessionNotCreatedException(
            "session not created: user data directory is already in use"
        )

    monkeypatch.setitem(
        command_line._COMMAND_SPECS["cpb"],
        "handler",
        fail_to_start_chrome,
    )

    with pytest.raises(
        SessionNotCreatedException,
        match="user data directory is already in use",
    ):
        command_line.main(["cpb", "notes.md"])


def test_gd_help_mentions_install_alias(capsys):
    command_line.main(["--help", "gd"])
    out = capsys.readouterr().out
    assert "--install" in out
    assert "alias.gd" in out
    assert "difftool.mygvim.cmd" in out


def test_root_error_mentions_subcommand_help_hint(capsys):
    with pytest.raises(SystemExit) as excinfo:
        command_line.main(["--definitely-not-a-real-option"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "***" in err
    assert "--help <subcommand>" in err


@pytest.mark.parametrize(
    "command, paths",
    [
        ("cpb", ["notes.md"]),
        ("wmatch", ["old.md", "new.md"]),
        ("wr", ["notes.md"]),
        ("wrchk", ["notes.md"]),
    ],
)
@pytest.mark.parametrize("before_paths", [False, True])
def test_wrapping_commands_share_option_definitions(
    command, paths, before_paths
):
    parser = command_line.build_parser()
    options = ["--wrapnumber", "72", "--trailing-dependent-phrase", "9"]
    arguments = options + paths if before_paths else paths + options
    namespace = parser.parse_args([command, *arguments])
    assert namespace.wrapnumber == 72
    assert (
        getattr(
            namespace,
            "trailing_dependent_phrase",
            getattr(namespace, "punctuation_slop", None),
        )
        == 9
    )
    actions = {
        action.dest: action
        for action in parser._pydifft_subparsers[command]._actions
    }
    phrase = actions.get(
        "trailing_dependent_phrase", actions.get("punctuation_slop")
    )
    assert phrase.default == 20
    assert "--trailing-dependent-phrase" in phrase.option_strings


@pytest.mark.parametrize(
    "command, paths",
    [
        ("cpb", ["notes.md"]),
        ("wmatch", ["old.md", "new.md"]),
        ("wr", ["notes.md"]),
        ("wrchk", ["notes.md"]),
    ],
)
@pytest.mark.parametrize(
    "options",
    [
        ["--wrapnumber", "0"],
        ["--trailing-dependent-phrase", "-1"],
    ],
)
def test_wrapping_commands_reject_invalid_limits(command, paths, options):
    with pytest.raises(SystemExit) as error:
        command_line.main([command, *options, *paths])
    assert error.value.code == 2


@pytest.mark.parametrize("distance", [0, 19, 20])
def test_wmatch_cli_applies_shared_dependent_phrase_option(tmp_path, distance):
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    prefix = "These measurements characterize the dynamics,"
    text = prefix + " short phrase.\n"
    old.write_text("Earlier statement.\n")
    new.write_text(text)
    command_line.main(
        [
            "wmatch",
            str(old),
            str(new),
            "--wrapnumber",
            str(len(prefix) + 20),
            "--trailing-dependent-phrase",
            str(distance),
        ]
    )
    expected = prefix + "\nshort phrase.\n" if distance == 20 else text
    assert new.read_text() == expected


def test_cpb_build_passes_dependent_phrase_option_to_source_lint(monkeypatch):
    from pydifftools import continuous, wrap_sentences

    calls = []

    def capture_fix_options(filename, **options):
        calls.append((filename, options))
        raise RuntimeError("options captured")

    monkeypatch.setattr(
        wrap_sentences, "autofix_markdown_file", capture_fix_options
    )
    with pytest.raises(RuntimeError, match="options captured"):
        continuous.run_pandoc(
            "notes.md",
            "notes.html",
            wrapnumber=72,
            trailing_dependent_phrase=9,
        )
    assert calls == [
        (
            "notes.md",
            {"wrapnumber": 72, "git_head": True, "punctuation_slop": 9},
        )
    ]
