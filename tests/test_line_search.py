import json
import re
import shutil
import subprocess

from lxml import html
import pytest

from pydifftools.command_line import main
from pydifftools.line_search import (
    extract_source_lines, finish_source_map, mark_source_lines,
)


@pytest.mark.parametrize("args", [[], ["old phrase"], ["12abc", "a.md"],
                                  ["0", "a.md"], ["2", "a.md", "extra"]])
def test_malformed_mfs_suggests_vimrc(args, capsys):
    with pytest.raises(SystemExit) as caught:
        main(["mfs", *args])
    assert caught.value.code == 2
    message = capsys.readouterr().err
    assert "nnoremap" in message
    assert "shellescape(expand('%:p'), 1)" in message


def test_line_map_strips_rendered_prefixes(tmp_path):
    if not shutil.which("pandoc"):
        pytest.skip("pandoc is unavailable")
    source = tmp_path / "notes.md"
    original = (
        "# Heading\n\nFirst H<sub>2</sub>O line\n"
        '"Quoted words" followed by prose.\n\n'
        "Repeated prose.\n\nRepeated prose.\n"
    )
    source.write_text(original)
    output = tmp_path / "notes.html"
    baseline = subprocess.check_output(
        ["pandoc", "-s", "-f", "markdown", "-t", "html", str(source)],
        text=True,
    )
    marked, nonce = mark_source_lines(original, source)
    output.write_text(subprocess.check_output(
        ["pandoc", "-s", "-f", "markdown", "-t", "html"],
        input=marked, text=True,
    ))
    assert nonce + "0000003XFirst" in marked
    assert nonce + "0000004Xfollowed" in marked
    assert nonce in output.read_text()
    extract_source_lines(output, nonce, source)
    mapped = output.read_text()
    assert nonce not in mapped
    mapped_text, baseline_text = (
        re.sub(r"\s+", " ", html.fromstring(page).find("body").text_content())
        for page in (mapped, baseline)
    )
    assert mapped_text == baseline_text
    script = html.document_fromstring(mapped).get_element_by_id(
        "pydifft-line-map"
    )
    entries = json.loads(script.text)
    assert [line for _, path, locations in entries
            for _, line in locations if path == str(source)] == [3, 4, 6, 8]


def test_qmdb_map_keeps_included_file_identity(tmp_path):
    root = html.document_fromstring(
        "<html><head></head><body><section><p>Same</p><p>Same</p>"
        "</section></body></html>"
    )
    for block, source in zip(root.xpath("//p"), ("a.qmd", "sub/a.qmd")):
        block.set("data-pydifft-line-map", json.dumps([source, [[0, 42]]]))
    finish_source_map(root, tmp_path)
    assert not root.xpath("//*[@data-pydifft-line-map]")
    entries = json.loads(root.get_element_by_id("pydifft-line-map").text)
    assert entries == [
        [[0, 0], str(tmp_path / "a.qmd"), [[0, 42]]],
        [[0, 1], str(tmp_path / "sub/a.qmd"), [[0, 42]]],
    ]


def test_chrome_search_preserves_copy_and_layout(tmp_path, chrome_driver_path):
    from pathlib import Path

    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

    source = tmp_path / "copy.md"
    source.write_text(
        "First H<sub>2</sub>O and *emphasis* with "
        "[linked words](https://example.com) and enough prose to wrap.\n"
        "Second line.\n\n    preformatted   text\n"
    )
    baseline = tmp_path / "baseline.html"
    mapped = tmp_path / "mapped.html"
    if not shutil.which("pandoc"):
        pytest.skip("pandoc is unavailable")
    pandoc = ["pandoc", "-s", "-f", "markdown", "-t", "html", "--wrap=none"]
    original = source.read_text()
    marked, nonce = mark_source_lines(original, source)
    for page, markdown in ((baseline, original), (mapped, marked)):
        content = subprocess.check_output(pandoc, input=markdown, text=True)
        page.write_text(content.replace(
            "</head>", "<style>p{margin-top:600px}</style></head>"
        ))
    extract_source_lines(mapped, nonce, source)
    script = (
        Path(__file__).parents[1] / "pydifftools" / "line_search.js"
    ).read_text()
    mapped.write_text(mapped.read_text().replace(
        "</head>",
        "<script>window.pydifftSourceJumpEndpoint='/jump';"
        + script + "</script></head>",
    ))
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    with webdriver.Chrome(
        service=Service(chrome_driver_path), options=options
    ) as browser:
        browser.execute_cdp_cmd(
            "Browser.grantPermissions",
            {"permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]},
        )
        for width in (390, 1050):
            browser.set_window_size(width, 500)
            results = []
            for page in (baseline, mapped):
                browser.get(page.as_uri())
                bounds = browser.execute_script("""
                    const p = document.querySelector('p');
                    const range = document.createRange();
                    range.setStart(p, 0);
                    range.setEndAfter(document.querySelector('pre'));
                    getSelection().addRange(range);
                    p.scrollIntoView();
                    return [...range.getClientRects()].map(
                        r => [r.width, r.height, r.x, r.y]);
                """)
                ActionChains(browser).key_down(Keys.CONTROL).send_keys(
                    "c"
                ).key_up(Keys.CONTROL).perform()
                results.append(browser.execute_async_script("""
                    const done = arguments[arguments.length - 1];
                    const bounds = arguments[0];
                    navigator.clipboard.read().then(async items => {
                        const copied = {};
                        for (const item of items) {
                            for (const type of item.types) {
                                const blob = await item.getType(type);
                                copied[type] = await blob.text();
                            }
                        }
                        done([bounds, copied]);
                    }).catch(error => done(String(error)));
                """, bounds))
                browser.execute_script("""
                    const draft = document.createElement('div');
                    draft.contentEditable = 'true';
                    draft.id = 'email-draft';
                    document.body.appendChild(draft);
                    draft.focus();
                """)
                ActionChains(browser).key_down(Keys.CONTROL).send_keys(
                    "v"
                ).key_up(Keys.CONTROL).perform()
                results[-1].append(browser.execute_script("""
                    const draft = document.getElementById('email-draft');
                    const pasted = draft.innerHTML;
                    draft.remove();
                    const range = document.createRange();
                    range.selectNodeContents(document.querySelector('p'));
                    getSelection().removeAllRanges();
                    getSelection().addRange(range);
                    return pasted;
                """))
            assert isinstance(results[0], list), results[0]
            assert results[0] == results[1]
            assert set(results[1][1]) == {"text/plain", "text/html"}
            assert "pydifft-line" not in results[1][1]["text/html"]
            assert "preformatted   text" in results[1][2]
            result = browser.execute_script("""
                const before = getSelection().toString();
                if (window.pydifftForwardLine(arguments[0], 1000)) {
                    throw new Error('Unexpected jump to a distant line');
                }
                const moved = window.pydifftForwardLine(arguments[0], 2);
                const p = document.querySelector('p');
                const text = p.lastChild;
                const range = document.createRange();
                range.setStart(text, text.data.indexOf('Second') + 1);
                range.setEnd(text, text.data.indexOf('Second') + 2);
                const rect = range.getBoundingClientRect();
                window.fetch = (_url, options) => {
                    window.jump = JSON.parse(options.body);
                    return Promise.resolve();
                };
                p.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true,
                    clientX: rect.left, clientY: rect.top + rect.height / 2,
                }));
                [...document.querySelectorAll('button')].at(-1).click();
                const sameSelection = before === getSelection().toString();
                const glow = document.getElementById('pydifft-line-glow');
                const atLine = Math.abs(
                    glow.getBoundingClientRect().top - rect.top) <= 1;
                const blurred = getComputedStyle(glow).boxShadow !== 'none';
                glow.getAnimations()[0].finish();
                return [moved, sameSelection, window.jump, atLine, blurred];
            """, str(source))
            assert result == [
                True, True, {"source": str(source), "line": 2}, True, True
            ]
            WebDriverWait(browser, 2).until(
                lambda driver: driver.execute_script(
                    "return !document.getElementById('pydifft-line-glow');"
                )
            )


def test_markers_survive_crossref_and_multiline_math(tmp_path):
    if not shutil.which("pandoc") or not shutil.which("pandoc-crossref"):
        pytest.skip("pandoc and pandoc-crossref are required")
    source = tmp_path / "refs.md"
    original = (
        "# Setup {#sec:setup}\n\n"
        "As noted in @sec:setup, we can see the general pattern.\n"
        "This corresponds to the equation\n"
        "$$x =\n"
        "y$$" "{#eq:sample}\n"
        "which describes what happens in the next part.\n"
        "Several words follow on another source line.\n\n"
        "![Caption](image.png){#fig:sample}\n"
    )
    source.write_text(original)
    marked, nonce = mark_source_lines(original, source)
    output = tmp_path / "refs.html"
    output.write_text(subprocess.check_output(
        ["pandoc", "-s", "-f", "markdown", "-t", "html", "--mathjax",
         "--filter", "pandoc-crossref", "--number-sections",
         "-M", "linkReferences=true"],
        input=marked, text=True, stderr=subprocess.DEVNULL,
    ))
    extract_source_lines(output, nonce, source)
    root = html.document_fromstring(output.read_text())
    assert root.xpath('//a[@href="#sec:setup"]')
    assert root.get_element_by_id("fig:sample") is not None
    entries = json.loads(root.get_element_by_id("pydifft-line-map").text)
    assert [line for _, _, points in entries for _, line in points] == [
        3, 4, 7, 8,
    ]
