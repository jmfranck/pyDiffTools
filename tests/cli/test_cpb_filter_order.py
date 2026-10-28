import pytest

from pydifftools.continuous import run_pandoc


@pytest.mark.parametrize("declaration", [
    "  - filters/second.lua\n  - ./first.lua\n  - first.lua\n",
    "  - filters/second.lua\n  - linked.lua\n  - first.lua\n",
])
def test_declared_filters_run_once_in_order_before_crossref(
    tmp_path, monkeypatch, declaration,
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "filters").mkdir()
    first = project / "first.lua"
    second = project / "filters" / "second.lua"
    after = project / "after.lua"
    for path in [first, second, after]:
        path.write_text("return {}\n")
    (project / "linked.lua").symlink_to(first)
    markdown = project / "notes.md"
    markdown.write_text(
        "---\nfilters-before-crossref:\n" + declaration + "---\n\n# Title\n"
    )
    html = tmp_path / "notes.html"
    commands = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda name: "/tool"
    )

    def fake_run(command):
        commands.append(command)
        html.write_text("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)
    run_pandoc(str(markdown), str(html))
    command, = commands
    filters = [
        (token, command[index + 1])
        for index, token in enumerate(command[:-1])
        if token in {"--filter", "--lua-filter", "--citeproc"}
    ]
    assert filters[:3] == [
        ("--lua-filter", str(second)),
        ("--lua-filter", str(first)),
        ("--filter", "pandoc-crossref"),
    ]
    lua_paths = [value for token, value in filters if token == "--lua-filter"]
    assert lua_paths == [str(second), str(first), str(after)]


@pytest.mark.parametrize("setting, error, message", [
    ("[missing.lua]", FileNotFoundError, "file not found: 'missing.lua'"),
    ("[.]", FileNotFoundError, "file not found: '.'"),
    ("first.lua", ValueError, "must be a list of file paths"),
    ("[1]", ValueError, "must be a list of file paths"),
    ("null", ValueError, "must be a list of file paths"),
])
def test_invalid_declared_filters_fail_before_pandoc(
    tmp_path, monkeypatch, setting, error, message,
):
    markdown = tmp_path / "notes.md"
    markdown.write_text(
        f"---\nfilters-before-crossref: {setting}\n---\n\n# Title\n"
    )
    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda name: "/tool"
    )
    with pytest.raises(error, match=message):
        run_pandoc(str(markdown), str(tmp_path / "notes.html"))
