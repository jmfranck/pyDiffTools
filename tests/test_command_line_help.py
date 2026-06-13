import time

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
