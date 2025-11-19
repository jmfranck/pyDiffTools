import pathlib
import subprocess
import pytest

from pydifftools.flowchart.graph import write_dot_from_yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def test_svg_render(tmp_path):
    dot_file = tmp_path / 'graph.dot'
    svg_file = tmp_path / 'graph.svg'
    tmp_yaml = tmp_path / 'graph.yaml'
    fixture_yaml = pathlib.Path(__file__).with_name('magnet_setup.yaml')
    tmp_yaml.write_text(fixture_yaml.read_text())
    write_dot_from_yaml(tmp_yaml, dot_file)
    subprocess.run(['dot', '-Tsvg', str(dot_file), '-o', str(svg_file)], check=True)
    options = Options()
    options.add_argument('--headless=new')
    try:
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        pytest.skip('chromedriver not available')
    driver.get('file://' + str(svg_file.resolve()))
    driver.find_element('tag name', 'svg')
    driver.quit()
