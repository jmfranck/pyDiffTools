import pathlib
import shutil

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from pydifftools.flowchart.watch_graph import (
    FlowchartPreviewServer,
    GraphEventHandler,
    _reload_svg,
    build_graph,
)

VIEW_JS = (
    "const p=window.wgrphPanZoom;const s=p.getSizes();"
    "return {z:s.realZoom,x:p.getPan().x,y:p.getPan().y,w:s.width,"
    "h:s.height,vx:s.viewBox.x,vy:s.viewBox.y,vw:s.viewBox.width,"
    "vh:s.viewBox.height};"
)


@pytest.fixture
def preview(tmp_path):
    if shutil.which("dot") is None:
        pytest.skip("graphviz not available")
    yaml_file = tmp_path / "graph.yaml"
    yaml_file.write_text(
        pathlib.Path(__file__).with_name("magnet_setup.yaml").read_text()
    )
    handler = GraphEventHandler(
        yaml_file,
        yaml_file.with_suffix(".dot"),
        yaml_file.with_suffix(".svg"),
        debounce=0,
    )
    handler.data = build_graph(
        handler.yaml_file, handler.dot_file, handler.svg_file, 55
    )
    server = FlowchartPreviewServer(handler)
    server.start()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1200,800")
    try:
        driver = webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"), options=options
        )
    except Exception:
        server.stop()
        pytest.skip("chromedriver not available")
    driver.get(server.base_url)
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script("return !!window.wgrphPanZoom")
    )
    yield driver, server
    driver.quit()
    server.stop()


def _view(driver):
    return driver.execute_script(VIEW_JS)


def _home_matches(view):
    # Whole graph fit in the viewport, pinned to the top, centered in x.
    assert view["vw"] * view["z"] <= view["w"] + 0.5
    assert view["vh"] * view["z"] <= view["h"] + 0.5
    assert min(
        abs(view["vw"] * view["z"] - view["w"]),
        abs(view["vh"] * view["z"] - view["h"]),
    ) < 0.5
    assert view["y"] == pytest.approx(-view["vy"] * view["z"], abs=0.5)
    assert view["x"] + view["vx"] * view["z"] == pytest.approx(
        (view["w"] - view["vw"] * view["z"]) / 2, abs=0.5
    )


def _drag(driver, embed, start, end):
    # Offsets are measured from the top-left of the embed; Selenium's element
    # offsets are measured from the element center.
    rect = embed.rect
    ActionChains(driver).move_to_element_with_offset(
        embed, start[0] - rect["width"] / 2, start[1] - rect["height"] / 2
    ).click_and_hold().move_by_offset(
        (end[0] - start[0]) / 2, (end[1] - start[1]) / 2
    ).move_by_offset(
        (end[0] - start[0]) / 2, (end[1] - start[1]) / 2
    ).release().perform()


def test_viewport_fills_window_and_starts_fit_at_top(preview):
    driver, _ = preview
    layout = driver.execute_script(
        "const e=document.getElementById('svg-view').getBoundingClientRect();"
        "const p=document.querySelector('p');"
        "const f=p.getBoundingClientRect().top"
        "-parseFloat(getComputedStyle(p).marginTop);"
        "return {top:e.top,bottom:e.bottom,width:e.width,footer:f,"
        "win_w:window.innerWidth,win_h:window.innerHeight,"
        "scroll:document.documentElement.scrollHeight};"
    )
    assert layout["top"] == 0
    assert layout["width"] == layout["win_w"]
    assert layout["bottom"] == pytest.approx(layout["footer"], abs=1)
    assert layout["scroll"] <= layout["win_h"]
    _home_matches(_view(driver))


def test_wheel_toolbar_and_box_zoom_leave_browser_zoom_alone(preview):
    driver, _ = preview
    embed = driver.find_element("id", "svg-view")
    home = _view(driver)
    ActionChains(driver).scroll_from_origin(
        ScrollOrigin.from_element(embed), 0, -300
    ).perform()
    zoomed = _view(driver)
    assert zoomed["z"] > home["z"] * 1.1
    assert driver.execute_script("return window.visualViewport.scale") == 1
    assert driver.execute_script("return window.devicePixelRatio") == 1

    driver.find_element("id", "wgrph-home").click()
    _home_matches(_view(driver))
    driver.find_element("id", "wgrph-zoom-in").click()
    assert _view(driver)["z"] == pytest.approx(home["z"] * 1.25)
    driver.find_element("id", "wgrph-home").click()

    driver.find_element("id", "wgrph-box-zoom").click()
    assert "active" in driver.find_element(
        "id", "wgrph-box-zoom"
    ).get_attribute("class")
    _drag(driver, embed, (100, 100), (300, 200))
    boxed = _view(driver)
    factor = min(home["w"] / 200, home["h"] / 100)
    assert boxed["z"] == pytest.approx(home["z"] * factor, rel=0.05)
    # The selected box center (200, 150) moves to the viewport center.
    # Selenium rounds pointer offsets to whole pixels, and that sub-pixel
    # error is magnified by the zoom factor.
    graph_x = (200 - home["x"]) / home["z"]
    graph_y = (150 - home["y"]) / home["z"]
    assert graph_x * boxed["z"] + boxed["x"] == pytest.approx(
        home["w"] / 2, abs=1.5 * factor
    )
    assert graph_y * boxed["z"] + boxed["y"] == pytest.approx(
        home["h"] / 2, abs=1.5 * factor
    )
    assert driver.execute_script("return window.visualViewport.scale") == 1


def test_links_navigate_only_on_plain_click(preview):
    driver, server = preview
    embed = driver.find_element("id", "svg-view")
    link_center = driver.execute_script(
        "const t=document.getElementById('svg-view').getSVGDocument()"
        ".querySelector('a text').getBoundingClientRect();"
        "return [t.x+t.width/2,t.y+t.height/2];"
    )
    # A pan that ends on a task name must not navigate.
    before = _view(driver)
    _drag(
        driver,
        embed,
        (link_center[0] - 60, link_center[1] + 40),
        link_center,
    )
    after = _view(driver)
    assert after["x"] == pytest.approx(before["x"] + 60, abs=2)
    assert "t=" not in driver.current_url
    # Put the link back where it was and click it.
    driver.find_element("id", "wgrph-home").click()
    rect = embed.rect
    ActionChains(driver).move_to_element_with_offset(
        embed,
        link_center[0] - rect["width"] / 2,
        link_center[1] - rect["height"] / 2,
    ).click().perform()
    WebDriverWait(driver, 10).until(lambda d: "t=" in d.current_url)
    assert driver.current_url.startswith(server.base_url)


@pytest.mark.parametrize("query", ["", "?t=Report", "?d=1&p=1"])
def test_live_reload_keeps_pan_and_zoom(preview, query):
    driver, server = preview
    driver.get(server.base_url + query)
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script("return !!window.wgrphPanZoom")
    )
    nodes_before = driver.execute_script(
        "return Array.from(document.getElementById('svg-view')"
        ".getSVGDocument().querySelectorAll('g.node title'),n=>n.textContent)"
    )
    embed = driver.find_element("id", "svg-view")
    ActionChains(driver).scroll_from_origin(
        ScrollOrigin.from_element(embed), 0, -300
    ).perform()
    _drag(driver, embed, (400, 300), (450, 340))
    before = _view(driver)
    _reload_svg(driver, server.svg_url)
    nodes_after = driver.execute_script(
        "return Array.from(document.getElementById('svg-view')"
        ".getSVGDocument().querySelectorAll('g.node title'),n=>n.textContent)"
    )
    assert nodes_after == nodes_before
    after = _view(driver)
    assert after["z"] == pytest.approx(before["z"])
    assert after["x"] == pytest.approx(before["x"])
    assert after["y"] == pytest.approx(before["y"])


def test_search_centers_tasks_without_zooming_and_cycles_after_reload(preview):
    driver, server = preview
    handler = server.event_handler
    handler.yaml_file.write_text(
        "nodes:\n"
        "  alpha:\n"
        "    text: Sample sample at <b>room</b> temperature (test) μ\n"
        "  beta:\n"
        "    text: A sample for the experiment\n"
        "  gamma:\n"
        "    text: A completed sample\n"
        "    style: completed\n"
    )
    handler.data = build_graph(
        handler.yaml_file, handler.dot_file, handler.svg_file, 25
    )
    driver.get(server.base_url)
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script("return !!window.wgrphPanZoom")
    )
    driver.set_window_size(2400, 1600)
    WebDriverWait(driver, 10).until(lambda d: _view(d)["w"] == 2400)
    driver.find_element("id", "wgrph-actual-size").click()
    driver.find_element("id", "wgrph-zoom-in").click()
    chosen_zoom = _view(driver)["z"]
    driver.find_element("id", "wgrph-search").click()
    field = driver.find_element("id", "wgrph-search-input")
    field.send_keys("sAmPlE")
    status = driver.find_element("id", "wgrph-search-status")
    assert status.text == "1 of 4"
    for key, expected, task in (
        (Keys.NULL, "1 of 4", "alpha"),
        (Keys.TAB, "2 of 4", "alpha"),
        (Keys.TAB, "3 of 4", "beta"),
        (Keys.TAB, "4 of 4", "gamma"),
        (Keys.TAB, "1 of 4", "alpha"),
        (Keys.SHIFT + Keys.TAB, "4 of 4", "gamma"),
    ):
        field.send_keys(key)
        assert status.text == expected
        assert _view(driver)["z"] == pytest.approx(chosen_zoom)
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                "const doc=document.getElementById('svg-view')"
                ".getSVGDocument();"
                "const node=Array.from(doc.querySelectorAll('g.node')).find("
                "n=>n.getAttribute('data-source-name')===arguments[0]);"
                "const b=node.getBoundingClientRect();"
                "const s=window.wgrphPanZoom.getSizes();"
                "return Math.abs(b.x+b.width/2-s.width/2)<2 &&"
                "Math.abs(b.y+b.height/2-s.height/2)<2;",
                task,
            )
        )
        geometry = driver.execute_script(
            "const doc=document.getElementById('svg-view').getSVGDocument();"
            "const node=Array.from(doc.querySelectorAll('g.node')).find("
            "n=>n.getAttribute('data-source-name')===arguments[0]);"
            "const bounds=node.getBoundingClientRect();"
            "const rect=doc.querySelector('#wgrph-search-highlight rect')"
            ".getBoundingClientRect();"
            "return {x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2,"
            "highlightWidth:rect.width,highlightHeight:rect.height};",
            task,
        )
        view = _view(driver)
        assert geometry["x"] == pytest.approx(view["w"] / 2, abs=2)
        assert geometry["y"] == pytest.approx(view["h"] / 2, abs=2)
        assert geometry["highlightWidth"] > 0
        assert geometry["highlightHeight"] > 0
    assert driver.execute_script("return document.activeElement.id") == (
        "wgrph-search-input"
    )
    assert driver.execute_script("return window.visualViewport.scale") == 1
    _reload_svg(driver, server.svg_url)
    assert status.text == "4 of 4"
    field.send_keys(Keys.TAB)
    assert status.text == "1 of 4"
    assert _view(driver)["z"] == pytest.approx(chosen_zoom)
    driver.find_element("id", "wgrph-zoom-out").click()
    chosen_zoom = _view(driver)["z"]
    field.send_keys(Keys.TAB)
    assert status.text == "2 of 4"
    assert _view(driver)["z"] == pytest.approx(chosen_zoom)
    for query in ("room temperature", "(test)", "μ", "no such phrase"):
        field.send_keys(Keys.CONTROL + "a")
        field.send_keys(query)
        assert status.text == (
            "No matches" if query == "no such phrase" else "1 of 1"
        )
        assert _view(driver)["z"] == pytest.approx(chosen_zoom)
    field.send_keys(Keys.ESCAPE)
    assert not driver.find_element("id", "wgrph-search-panel").is_displayed()
    assert driver.execute_script(
        "return document.getElementById('svg-view').getSVGDocument()"
        ".getElementById('wgrph-search-highlight') === null"
    )


def test_resize_scales_graph_and_keeps_current_center(preview):
    driver, _ = preview
    home = _view(driver)
    driver.set_window_size(2400, 1600)
    WebDriverWait(driver, 10).until(lambda d: _view(d)["w"] > home["w"])
    _home_matches(_view(driver))
    assert _view(driver)["z"] > home["z"] * 1.5
    driver.find_element("id", "wgrph-zoom-in").click()
    _drag(
        driver, driver.find_element("id", "svg-view"), (400, 300), (450, 340)
    )
    before = _view(driver)
    for width, height in ((1000, 700), (1800, 1000), (2400, 1600)):
        driver.set_window_size(width, height)
        WebDriverWait(driver, 10).until(lambda d: _view(d)["w"] == width)
        after = _view(driver)
        factor = min(after["w"] / after["vw"], after["h"] / after["vh"]) / min(
            before["w"] / before["vw"], before["h"] / before["vh"]
        )
        assert after["z"] == pytest.approx(before["z"] * factor)
        for axis, size in (("x", "w"), ("y", "h")):
            assert (after[size] / 2 - after[axis]) / after["z"] == (
                pytest.approx((before[size] / 2 - before[axis]) / before["z"])
            )
        before = after


def test_actual_size_shows_native_font_pixels_and_preserves_center(preview):
    driver, server = preview
    for width, height in ((1200, 800), (2400, 1600)):
        driver.set_window_size(width, height)
        driver.find_element("id", "wgrph-home").click()
        before = _view(driver)
        graph_scale = driver.execute_script(
            "const doc=document.getElementById('svg-view').getSVGDocument();"
            "return doc.querySelector('.svg-pan-zoom_viewport')"
            ".getScreenCTM().inverse().multiply(doc.querySelector('text')"
            ".getScreenCTM()).a;"
        )
        button = driver.find_element("id", "wgrph-actual-size")
        assert button.text == "1:1"
        button.click()
        after = _view(driver)
        assert after["z"] == pytest.approx(1 / graph_scale)
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                "const doc=document.getElementById('svg-view')"
                ".getSVGDocument();"
                "return Math.abs(doc.querySelector('text')"
                ".getScreenCTM().a-1)<1e-6;"
            )
        )
        for axis, size in (("x", "w"), ("y", "h")):
            assert (after[size] / 2 - after[axis]) / after["z"] == (
                pytest.approx((before[size] / 2 - before[axis]) / before["z"])
            )
        pixels = driver.execute_script(
            "const doc=document.getElementById('svg-view').getSVGDocument();"
            "const text=doc.querySelector('text');"
            "const font=parseFloat(doc.defaultView.getComputedStyle(text)"
            ".fontSize);return {font:font,"
            "rendered:font*text.getScreenCTM().a};"
        )
        assert pixels["rendered"] == pytest.approx(pixels["font"])
        assert driver.execute_script("return window.visualViewport.scale") == 1
        _reload_svg(driver, server.svg_url)
        assert _view(driver)["z"] == pytest.approx(after["z"])
