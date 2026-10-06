import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from pydifftools import source_jump
from pydifftools.continuous import append_autorefresh


@pytest.fixture
def editor_process(monkeypatch):
    process = MagicMock()
    process.__enter__.return_value = process
    process.returncode = 0
    launch = MagicMock(return_value=process)
    monkeypatch.setattr(source_jump.subprocess, "Popen", launch)
    return launch, process


def test_jump_to_source_finds_wrapped_markdown_and_logs_command(
    editor_process, tmp_path, capsys
):
    launch, process = editor_process
    source = tmp_path / "plan with spaces.md"
    source.write_text(
        "Heading\n\nAn **Added**\n_Title_ with ~~strike~~, "
        "H~2~O and x^2^!\n"
    )

    source_jump.jump_to_source(
        source,
        "An Added Title with strike, H\uE0002\uE000O and x\uE0002\uE000!",
    )

    command = launch.call_args.args[0]
    assert command == [
        "bash", "-ic", 'gvim "$@"', "pydifft",
        "--servername", "GVIM", "--remote", "+3", str(source),
    ]
    process.wait.assert_called_once_with(timeout=10)
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 2
    assert output[0].startswith("pydifft source regex: ")
    pattern = output[0].removeprefix("pydifft source regex: ")
    assert re.search(pattern, source.read_text()).group().startswith("An")
    assert "Added" in pattern
    assert re.search(pattern, "An Added Title with strike, H~2~O and x^2^!")
    assert output[1] == "pydifft source command: " + shlex.join(command)


def test_plain_words_do_not_allow_markdown_between_letters(
    editor_process, tmp_path, capsys
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("or**din**ary H~2~O\nordinary H2O\n")

    source_jump.jump_to_source(source, "ordinary H2O")

    assert launch.call_args.args[0][-2] == "+2"
    pattern = capsys.readouterr().out.splitlines()[0].split(": ", 1)[1]
    assert re.fullmatch(pattern, "ordinary H2O")
    assert re.search(pattern, "or**din**ary H~2~O") is None


def test_markdown_tolerance_at_word_boundaries_includes_punctuation(
    editor_process, tmp_path, capsys
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("**ordinary**, _words_!\n")

    source_jump.jump_to_source(source, "ordinary, words!")

    assert launch.call_args.args[0][-2] == "+1"
    pattern = capsys.readouterr().out.splitlines()[0].split(": ", 1)[1]
    assert re.fullmatch(pattern, "ordinary**, _words_!")
    assert re.search(pattern, "ordinary; words!") is None


@pytest.mark.parametrize(
    "markdown, phrase",
    [
        ("Copper `Conductivity` walls.", "Copper Conductivity walls."),
        ("The quality factor $Q_0$.", "The quality factor ."),
        (
            "Before $$Q_0 = \\frac{a}{b}$$ after.",
            "Before after.",
        ),
        ("Before $x + \\$5$ after.", "Before after."),
        ("See @fig:resonator for details.", "See for details."),
    ],
)
def test_jump_to_source_matches_code_and_omitted_rendered_constructs(
    editor_process, tmp_path, markdown, phrase
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("Heading\n" + markdown + "\n")

    source_jump.jump_to_source(source, phrase)

    assert launch.call_args.args[0][-2] == "+2"


@pytest.mark.parametrize(
    "markdown",
    [
        "Before extra words after.",
        "Before $$x$$ extra words $$y$$ after.",
        "Before \\$5 extra words $x$ after.",
    ],
)
def test_jump_to_source_does_not_skip_ordinary_prose(
    editor_process, tmp_path, markdown
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text(markdown + "\n")

    with pytest.raises(ValueError, match="No source match"):
        source_jump.jump_to_source(source, "Before after.")

    launch.assert_not_called()


def test_jump_to_source_keeps_case_and_punctuation_literal(
    editor_process, tmp_path, capsys
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("Result A/B (x+2).\nResult A.B (x+2).\n")

    source_jump.jump_to_source(source, "Result A.B (x+2).")
    assert launch.call_args.args[0][-2] == "+2"
    launch.reset_mock()
    with pytest.raises(ValueError, match="No source match"):
        source_jump.jump_to_source(source, "result A.B (x+2).")
    launch.assert_not_called()
    assert "pydifft source regex:" in capsys.readouterr().out


def test_jump_to_source_reports_multiple_matches_and_uses_first(
    editor_process, tmp_path, capsys
):
    launch, _process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("heading\n**Same** text\n\nSame text\n")

    source_jump.jump_to_source(source, "Same text")

    assert launch.call_args.args[0][-2] == "+2"
    assert "lines [2, 4]; using line 2" in capsys.readouterr().out


@pytest.mark.parametrize("phrase", ["... !!!", " ** _ ~~ ^ ", ""])
def test_jump_to_source_rejects_text_without_searchable_words(
    editor_process, phrase
):
    launch, _process = editor_process

    with pytest.raises(ValueError, match="no searchable words"):
        source_jump.jump_to_source("plan.yaml", phrase)
    launch.assert_not_called()


def test_jump_to_source_timeout_stops_wrapper_process_group(
    editor_process, tmp_path, monkeypatch
):
    _launch, process = editor_process
    source = tmp_path / "plan.md"
    source.write_text("Needle\n")
    process.pid = 12345
    process.wait.side_effect = subprocess.TimeoutExpired("gvim", 10)
    kill_group = MagicMock()
    monkeypatch.setattr(source_jump.os, "killpg", kill_group)

    with pytest.raises(subprocess.TimeoutExpired):
        source_jump.jump_to_source(source, "Needle")

    kill_group.assert_called_once_with(12345, signal.SIGKILL)


def test_editor_launch_is_detached_and_exposes_stdout_and_stderr(
    monkeypatch, tmp_path, capfd
):
    source = tmp_path / "plan.md"
    source.write_text("Needle\n")
    popen = subprocess.Popen

    def launch_probe(command, **kwargs):
        # Exercise the real child-process settings without launching gvim.
        return popen(
            [
                sys.executable, "-c",
                "import os, sys; "
                "assert os.getsid(0) == os.getpid(); "
                "assert sys.stdin.read() == ''; "
                "print('editor stdout'); "
                "print('editor stderr', file=sys.stderr)",
            ],
            **kwargs,
        )

    monkeypatch.setattr(source_jump.subprocess, "Popen", launch_probe)

    source_jump.jump_to_source(source, "Needle")

    captured = capfd.readouterr()
    assert "editor stdout" in captured.out
    assert "editor stderr" in captured.out
    assert captured.err == ""


def test_browser_preserves_tag_boundaries_for_source_matching(
    monkeypatch, tmp_path
):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    browser = webdriver.Chrome(
        service=Service("/usr/bin/chromedriver"), options=options
    )
    launch = MagicMock()
    launch.return_value.__enter__.return_value.returncode = 0
    try:
        html = tmp_path / "preview.html"
        html.write_text("<html><body></body></html>")
        browser.get(html.as_uri())
        browser.execute_script(
            "window.pydifftSourceJumpEndpoint = 'http://localhost/jump';"
            "window.fetch = function (url, options) {"
            "  window.sentPhrase = options.body;"
            "  return Promise.resolve();"
            "};"
        )
        browser.execute_script(
            (Path(source_jump.__file__).parent / "flowchart/source_jump.js")
            .read_text()
        )
        examples = [
            (
                "A vacuum-filled closed cylindrical resonator, meshed "
                "once and then run through Palace twice: first with "
                "perfect-conductor (PEC) walls to reveal the analytical "
                "mode frequencies, then with copper <code>Conductivity"
                "</code> walls to extract a physical unloaded quality "
                "factor <span class='math inline'>Q<sub>0</sub></span>.",
                "A vacuum-filled closed cylindrical resonator, meshed "
                "once and then run through Palace twice: first with "
                "perfect-conductor (PEC) walls to reveal the analytical "
                "mode frequencies, then with copper Conductivity walls "
                "to extract a physical unloaded quality factor .",
                "A vacuum-filled closed cylindrical resonator,\n"
                "    meshed once and then run through Palace\n"
                "    twice: first with perfect-conductor (PEC)\n"
                "    walls to reveal the analytical mode\n"
                "    frequencies,\n"
                "    then with copper `Conductivity` walls to\n"
                "    extract a physical unloaded quality factor\n"
                "    $Q_0$.",
            ),
            (
                "An <strong>Added</strong>\n<em>Title</em> with "
                "<del>strike</del>, H<sub>2</sub>O and x<sup>2</sup>!",
                "An Added Title with strike\uE000, "
                "H\uE0002\uE000O and x\uE0002\uE000!",
                "An **Added**\n_Title_ with ~~strike~~, H~2~O and x^2^!",
            ),
            (
                "or<!--comment-->dinary H2O",
                "ordinary H2O",
                "ordinary H2O",
            ),
            (
                "or<strong>din</strong>ary H<sub>2</sub>O",
                "or\uE000din\uE000ary H\uE0002\uE000O",
                "or**din**ary H~2~O",
            ),
            (
                "ordinary <em> </em> H<sub>2</sub>O",
                "ordinary H\uE0002\uE000O",
                "ordinary H~2~O",
            ),
            (
                "Earlier sentence. H<sub id='clicked'>2</sub>O is "
                "<strong>ordinary</strong>. Later sentence.",
                "H\uE0002\uE000O is ordinary\uE000.",
                "H~2~O is **ordinary**.",
            ),
        ]
        for rendered, expected, markdown in examples:
            phrase = browser.execute_script(
                "let block = document.getElementById('target');"
                "if (!block) {"
                "  block = document.createElement('p');"
                "  block.id = 'target';"
                "  document.body.appendChild(block);"
                "}"
                "block.innerHTML = arguments[0];"
                "const clicked = document.getElementById('clicked') || block;"
                "const range = document.createRange();"
                "range.setStart(clicked.firstChild, 0);"
                "document.caretRangeFromPoint = function () {return range;};"
                "clicked.dispatchEvent(new MouseEvent('contextmenu', {"
                "  bubbles: true, cancelable: true, clientX: 20, clientY: 20"
                "}));"
                "document.querySelector('#pydifft-source-jump-menu button')"
                "  .click();"
                "return window.sentPhrase;",
                rendered,
            )
            assert phrase == expected
            source = tmp_path / "plan.md"
            source.write_text("Heading\n" + markdown + "\n")
            with monkeypatch.context() as editor_patch:
                editor_patch.setattr(source_jump.subprocess, "Popen", launch)
                source_jump.jump_to_source(source, phrase)
            assert launch.call_args.args[0][-2] == "+2"
    finally:
        browser.quit()


def test_cpb_injects_the_live_endpoint_and_context_menu(tmp_path):
    html_file = tmp_path / "preview.html"
    html_file.write_text("<html><head></head><body>preview</body></html>")

    append_autorefresh(str(html_file), "http://127.0.0.1:3456/jump?token=abc")
    append_autorefresh(str(html_file), "http://127.0.0.1:3456/jump?token=new")

    html = html_file.read_text()
    assert html.count('id="pydifft-source-jump-config"') == 1
    assert html.count('id="pydifft-source-jump"') == 1
    assert "http://127.0.0.1:3456/jump?token=new" in html
    assert "Jump to source" in html


def test_source_jump_server_accepts_only_tokened_loopback_requests(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        source_jump,
        "jump_to_source",
        lambda path, phrase: calls.append((path, phrase)),
    )
    server = source_jump.SourceJumpServer(tmp_path / "plan.yaml")
    url = server.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(
                urllib.request.Request(
                    url.split("?", 1)[0] + "?token=wrong",
                    data=b"task key",
                    method="POST",
                )
            )
        assert error.value.code == 404

        phrase = "Task H\uE0002\uE000O"
        response = urllib.request.urlopen(
            urllib.request.Request(
                url, data=phrase.encode("utf-8"), method="POST"
            )
        )
        assert response.status == 204
        assert calls == [(str(tmp_path / "plan.yaml"), phrase)]
        assert server.httpd.server_address[0] == "127.0.0.1"
    finally:
        server.stop()
