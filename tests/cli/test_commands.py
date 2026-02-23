import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from pydifftools.continuous import run_pandoc
from pydifftools.command_line import mfs


def _make_cli_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    (stub_dir / "argcomplete.py").write_text(
        "def autocomplete(parser):\n    return None\n"
    )
    (stub_dir / "numpy.py").write_text(
        "def array(*args, **kwargs):\n    return []\n"
        "def cumsum(*args, **kwargs):\n    return []\n"
        "def argmin(*args, **kwargs):\n    return 0\n"
    )
    (stub_dir / "psutil.py").write_text("pass\n")
    bib_path = Path("~/testlib.bib").expanduser()
    bib_path.write_text("@book{dummy, title={Dummy}}\n")
    # Ensure CLI subprocesses can see conda-installed tools and libraries.
    env["PATH"] = f"/root/conda/bin:{env['PATH']}"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = (
            f"{stub_dir}:{repo_root}:/root/conda/lib/python3.12/site-packages:"
            f"{env['PYTHONPATH']}"
        )
    else:
        env["PYTHONPATH"] = (
            f"{stub_dir}:{repo_root}:/root/conda/lib/python3.12/site-packages"
        )
    env["PYDIFFTOOLS_FAKE_MATHJAX"] = "1"
    env["PYDIFFTOOLS_UPDATE_CHECK_LAST_RAN_UTC_DATE"] = time.strftime(
        "%Y-%m-%d", time.gmtime()
    )
    return env




def write_minimal_bibliography_and_csl(target_dir):
    # Create citation support files that run_pandoc requires.
    (target_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (target_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<style'
        ' xmlns="http://purl.org/net/xbiblio/csl" version="1.0"'
        ' class="in-text">\n  <info>\n    <title>Minimal</title>\n   '
        ' <id>minimal</id>\n    <updated>2023-01-01T00:00:00Z</updated>\n '
        ' </info>\n  <citation>\n    <layout>\n      <text'
        ' variable="title"/>\n    </layout>\n  </citation>\n  <bibliography>\n'
        '    <layout>\n      <text variable="title"/>\n    </layout>\n '
        ' </bibliography>\n</style>'
    )


def test_wgrph_missing_file(tmp_path):
    env = _make_cli_env(tmp_path)
    cmd = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "wgrph",
        str(tmp_path / "missing.yaml"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode != 0
    assert "YAML file not found" in proc.stderr


def test_tex2qmd_cli(tmp_path):
    env = _make_cli_env(tmp_path)
    sample = (
        Path(__file__).resolve().parents[1] / "fixtures" / "tex" / "sample.tex"
    )
    target = tmp_path / "example.tex"
    target.write_text(sample.read_text())
    cmd = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "tex2qmd",
        str(target),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=tmp_path
    )
    # --- NEW DEBUGGING LINES ---
    if proc.returncode != 0:
        print("--- Subprocess STDOUT ---")
        print(proc.stdout)
        print("--- Subprocess STDERR ---")
        print(proc.stderr)
        print("-------------------------")
    # ---------------------------
    assert proc.returncode == 0
    assert target.with_suffix(".qmd").exists()


def test_qmdinit_and_qmdb(tmp_path):
    env = _make_cli_env(tmp_path)
    project_dir = tmp_path / "proj"
    cmd_init = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "qmdinit",
        str(project_dir),
    ]
    proc_init = subprocess.run(
        cmd_init, capture_output=True, text=True, env=env
    )
    assert proc_init.returncode == 0
    mathjax = (
        project_dir / "_template" / "mathjax" / "es5" / "tex-mml-chtml.js"
    )
    assert mathjax.exists()
    cmd_build = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "qmdb",
        "--no-browser",
    ]
    proc_build = subprocess.run(
        cmd_build,
        capture_output=True,
        text=True,
        env=env,
        cwd=project_dir,
    )
    assert proc_build.returncode == 0
    built = project_dir / "_build" / "project1" / "subproject1" / "tasks.html"
    assert built.exists()


def test_markdown_outline_reorder(tmp_path):
    env = _make_cli_env(tmp_path)
    sample = (
        Path(__file__).resolve().parents[1] / "fixtures" / "md" / "sample.md"
    )
    target = tmp_path / "sample.md"
    target.write_text(sample.read_text())
    cmd_extract = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "xomd",
        str(target),
    ]
    proc_extract = subprocess.run(
        cmd_extract, capture_output=True, text=True, env=env
    )
    assert proc_extract.returncode == 0
    outline_path = tmp_path / "sample_outline.md"
    assert outline_path.exists()
    outline_path.write_text(
        "*\tProject Notes\n"
        "\t*\tSecond Topic\n"
        "\t*\tDeep Dive\n"
        "\t\t\t\t*\tHidden Notes\n"
        "\t*\tFirst Topic\n"
    )
    cmd_reorder = [
        sys.executable,
        "-m",
        "pydifftools.command_line",
        "xomdreorder",
        str(target),
    ]
    proc_reorder = subprocess.run(
        cmd_reorder, capture_output=True, text=True, env=env
    )
    assert proc_reorder.returncode == 0
    content = target.read_text()
    assert content.index("## Second Topic") < content.index("## First Topic")
    assert "##### Hidden Notes" in content


def test_cpb_hides_low_headers(tmp_path):
    env = _make_cli_env(tmp_path)

    # 1. Provide Markdown with a citation to avoid 'No citation element'
    # errors
    markdown_content = (
        "# Visible\n\n"
        "This text includes a reference [@dummy_ref].\n\n"
        "##### Hidden Header\nBody text.\n"
    )
    markdown_file = tmp_path / "notes.md"
    markdown_file.write_text(markdown_content)

    write_minimal_bibliography_and_csl(tmp_path)
    html_file = tmp_path / "notes.html"
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch.dict(os.environ, env, clear=False):
            run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)
    html_content = html_file.read_text()
    assert "h5, h6 { display: none; }" in html_content
    assert "h4" not in html_content.split("display:")[-1]


def test_mfs_starts_cpb_when_socket_missing(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nneedle\nomega\n")
    (tmp_path / "other.md").write_text("does not match\n")

    calls = {
        "connect": 0,
        "sendall": [],
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            calls["connect"] += 1
            if calls["connect"] == 1:
                raise OSError("socket not ready")

        def sendall(self, payload):
            calls["sendall"].append(payload)

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            with patch("pydifftools.command_line.os.fork", return_value=123):
                with patch("pydifftools.command_line.time.sleep"):
                    mfs("needle")
        assert calls["connect"] >= 2
        assert calls["sendall"] == [b"needle"]
    finally:
        os.chdir(cwd)


def test_mfs_waits_up_to_20_seconds_for_socket(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nneedle\nomega\n")

    calls = {
        "connect": 0,
        "sleep": 0,
    }

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            calls["connect"] += 1
            raise OSError("socket not ready")

        def sendall(self, _payload):
            return

        def close(self):
            return

    def fake_sleep(_seconds):
        calls["sleep"] += 1

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            with patch("pydifftools.command_line.os.fork", return_value=123):
                with patch("pydifftools.command_line.time.sleep", fake_sleep):
                    try:
                        mfs("needle")
                        assert False, "Expected mfs to raise RuntimeError"
                    except RuntimeError as exc:
                        assert "within 20 seconds" in str(exc)
        # one initial connect plus 80 retries gives a full 20-second wait
        # window
        assert calls["connect"] == 81
        assert calls["sleep"] == 80
    finally:
        os.chdir(cwd)


def test_run_pandoc_adds_css_lua_and_js_files_from_markdown_directory(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    (project_dir / "site.css").write_text("body { color: red; }\n")
    (project_dir / "print.css").write_text(
        "@media print { body { color: black; } }\n"
    )
    (project_dir / "cleanup.lua").write_text("return {}\n")
    (project_dir / "numbers.lua").write_text("return {}\n")
    (project_dir / "extras.js").write_text('console.log("extras");\n')
    (project_dir / "widgets.js").write_text('console.log("widgets");\n')
    html_file = tmp_path / "notes.html"
    captured_command = {}

    # Skip external tool checks and capture the exact pandoc command.
    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(command):
        captured_command["value"] = command
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write(
                '<html><head><script id="MathJax-script" '
                'src="MathJax-3.1.2/es5/tex-mml-chtml.js"></script></head>'
                "<body>ok</body></html>"
            )

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    css_pairs = []
    lua_pairs = []
    command = captured_command["value"]
    for index, token in enumerate(command[:-1]):
        if token == "--css":
            css_pairs.append(command[index + 1])
        if token == "--lua-filter":
            lua_pairs.append(command[index + 1])
    assert css_pairs == [
        str(project_dir / "print.css"),
        str(project_dir / "site.css"),
    ]
    assert lua_pairs == [
        str(project_dir / "cleanup.lua"),
        str(project_dir / "numbers.lua"),
    ]
    html_content = html_file.read_text()
    assert "MathJax-script" in html_content
    assert (
        '<script src="' + str(project_dir / "extras.js") + '"></script>'
    ) in html_content
    assert (
        '<script src="' + str(project_dir / "widgets.js") + '"></script>'
    ) in html_content


def test_run_pandoc_copies_comment_assets_when_comment_tags_present(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    markdown_file = project_dir / "notes.md"
    markdown_file.write_text("# Title\n\n<comment>hello</comment>\n")
    (project_dir / "references.bib").write_text(
        "@misc{dummy_ref, author={Author Name}, title={Title}, year={2023}}"
    )
    (project_dir / "style.csl").write_text(
        '<?xml version="1.0" encoding="utf-8"?><style '
        'xmlns="http://purl.org/net/xbiblio/csl" version="1.0"></style>'
    )
    html_file = tmp_path / "notes.html"

    monkeypatch.setattr(
        "pydifftools.continuous.shutil.which", lambda _name: "/usr/bin/tool"
    )

    def fake_run(_command):
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr("pydifftools.continuous.subprocess.run", fake_run)

    run_pandoc(str(markdown_file), str(html_file))

    assert (project_dir / "comments.css").exists()
    assert (project_dir / "comment_tags.lua").exists()
    assert (project_dir / "comment_toggle.js").exists()


def test_run_pandoc_comment_tag_regression_end_to_end(tmp_path):
    # This markdown reproduces the current failing mode where list content
    # inside <comment> leaks into the main body text.
    markdown_content = """Because these contributions have a smaller
linewidth and because the amplitude of the
derivative signal is inversely proportional
to the square of the linewidth,
the spectrum responds correspondingly dramatically
to contributions from the RMs with low local
concentration.
<comment>
☐ TODO:
	Include a comparison of actual lines in the
	plot.
</comment>
<comment>
☐ TODO:
	Make sure the git repo has the updated
	version of the plot that you crafted and
	presented on slack!!
</comment>
Correspondingly,
<comment>
☐ TODO:
Here, you want to guide people more
explicitly through exactly what you are
talking about:

* For people unaccustomed to ESR spectra, you
	want to specifically talk in terms of the
	"initial positive maximum" and the "final
	minimum".
* You need to be sure that you're
	explaining that in this concentration
	range, you transition from three resolved
	hyperfine lines to a single, broad line.
</comment>
ESR measurements at lower water loading include [@dummy_ref].

<comment>
☐ TODO:
	I think a lot of the following caption is
	description.
</comment>

::: {.comment-right}
☐ TODO:
It's still unclear what causes the low-$E_a$ region.
:::
"""
    markdown_file = tmp_path / "notes.md"
    html_file = tmp_path / "notes.html"
    markdown_file.write_text(markdown_content)
    write_minimal_bibliography_and_csl(tmp_path)

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)

    html_content = html_file.read_text()

    # Ensure comments generated from <comment> tags and .comment-right blocks
    # are rendered as bubbles in the output html.
    assert html_content.count('class="comment-pin"') >= 3
    assert 'class="comment-right"' in html_content

    # Regression assertion: this phrase should be present inside a comment
    # bubble tree, not in plain body nodes. This currently fails and captures
    # the leak where list text escapes from the <comment> block.
    phrase = 'For people unaccustomed to ESR spectra'
    assert phrase in html_content
    phrase_in_comment_tree = (
        '<div class="comment-overlay' in html_content
        and phrase in html_content.split('<div class="comment-overlay', 1)[1]
    )
    assert phrase_in_comment_tree


def test_comment_css_arrow_geometry_constants(tmp_path):
    # Keep explicit geometry values in test constants so future style edits can
    # update one place and immediately see behavior changes in this test.
    arrow_size_px = 8
    bubble_separation_rem = 0.5

    markdown_file = tmp_path / "notes.md"
    html_file = tmp_path / "notes.html"
    markdown_file.write_text(
        "Body [@dummy_ref].\n\n<comment>Inline bubble</comment>\n"
    )
    write_minimal_bibliography_and_csl(tmp_path)

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run_pandoc(str(markdown_file), str(html_file))
    finally:
        os.chdir(cwd)

    css_content = (tmp_path / "comments.css").read_text()

    # Left/right pointer triangles should use the configured arrow size.
    assert f"left: -{arrow_size_px}px;" in css_content
    assert f"right: -{arrow_size_px}px;" in css_content
    assert (
        f"border-width: {arrow_size_px}px {arrow_size_px}px {arrow_size_px}px 0;"
        in css_content
    )
    assert (
        f"border-width: {arrow_size_px}px 0 {arrow_size_px}px {arrow_size_px}px;"
        in css_content
    )

    # Bubble separation (gap) must match the configured value for both sides.
    assert f"left: {bubble_separation_rem}rem;" in css_content
    assert f"right: {bubble_separation_rem}rem;" in css_content
    assert f"--comment-gap: {bubble_separation_rem}rem;" in css_content


def test_mfs_errors_when_no_matching_markdown(tmp_path):
    (tmp_path / "notes.md").write_text("alpha\nbeta\n")

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            return

        def connect(self, _address):
            raise OSError("socket not ready")

        def sendall(self, _payload):
            return

        def close(self):
            return

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("pydifftools.command_line.socket.socket", FakeSocket):
            try:
                mfs("needle")
                assert False, "Expected mfs to raise RuntimeError"
            except RuntimeError as exc:
                assert "could not find the requested text" in str(exc)
    finally:
        os.chdir(cwd)
