import time

import pytest

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


def test_short_and_long_help_are_interchangeable_for_subcommand_help(capsys):
    command_line.main(["-h", "cpb"])
    short_out = capsys.readouterr().out
    command_line.main(["--help", "cpb"])
    long_out = capsys.readouterr().out
    assert "--comments-to-margin" in short_out
    assert "--comments-to-margin" in long_out


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
