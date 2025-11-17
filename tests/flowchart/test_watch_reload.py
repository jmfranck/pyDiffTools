import pathlib
import subprocess
import pytest

from pydifftools.flowchart.graph import write_dot_from_yaml
from pydifftools.flowchart.watch_graph import _reload_svg
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def test_reload_preserves_view(tmp_path):
    dot_file = tmp_path / 'graph.dot'
    svg_file = tmp_path / 'graph.svg'
    html_file = tmp_path / 'view.html'
    tmp_yaml = tmp_path / 'graph.yaml'
    fixture_yaml = pathlib.Path(__file__).with_name('magnet_setup.yaml')
    tmp_yaml.write_text(fixture_yaml.read_text())
    write_dot_from_yaml(tmp_yaml, dot_file)
    subprocess.run(['dot', '-Tsvg', dot_file, '-o', svg_file], check=True)
    html_file.write_text(
        "<html><body style='margin:0'>"
        f"<embed id='svg-view' type='image/svg+xml' src='{svg_file.name}'/>"
        "</body></html>"
    )
    options = Options()
    options.add_argument('--headless=new')
    try:
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        pytest.skip('chromedriver not available')
    driver.get(html_file.resolve().as_uri())
    driver.execute_script("document.body.style.zoom=1.5")
    driver.execute_script("window.scrollTo(0, 120)")
    zoom_before = driver.execute_script("return window.visualViewport.scale")
    scroll_before = driver.execute_script("return window.scrollY")
    _reload_svg(driver, svg_file)
    zoom_after = driver.execute_script("return window.visualViewport.scale")
    scroll_after = driver.execute_script("return window.scrollY")
    driver.quit()
    assert zoom_before == zoom_after
    assert scroll_before == scroll_after
