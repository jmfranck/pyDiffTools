import urllib.error
import urllib.request

import pytest

from pydifftools import source_jump
from pydifftools.continuous import append_autorefresh


def test_jump_to_source_uses_lowercase_words_with_swc_search(monkeypatch):
    calls = []
    monkeypatch.setattr(
        source_jump,
        "_run_gvim_shell_command",
        lambda *arguments: calls.append(arguments),
    )

    source_jump.jump_to_source("/tmp/plan.yaml", "An Added Title word!")

    assert calls == [
        ("/tmp/plan.yaml",),
        (
            "--servername",
            "GVIM",
            "--remote-send",
            "<C-\\><C-N>:SW! an added title word<CR>",
        ),
    ]


def test_jump_to_source_rejects_text_without_searchable_words(monkeypatch):
    monkeypatch.setattr(
        source_jump,
        "_run_gvim_shell_command",
        lambda *_args: pytest.fail("gvim should not be called"),
    )

    with pytest.raises(ValueError, match="no searchable words"):
        source_jump.jump_to_source("plan.yaml", "... !!!")


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

        response = urllib.request.urlopen(
            urllib.request.Request(url, data=b"Task key", method="POST")
        )
        assert response.status == 204
        assert calls == [(str(tmp_path / "plan.yaml"), "Task key")]
        assert server.httpd.server_address[0] == "127.0.0.1"
    finally:
        server.stop()
