"""Continuous Pandoc build utility that requires geckodriver."""

import time
import subprocess
import sys
import os
import re
import selenium
from selenium import webdriver
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from .command_registry import register_command


def run_pandoc(filename, html_file):
    if os.path.exists("MathJax-3.1.2"):
        has_local_jax = True
    else:
        has_local_jax = False
        print("you don't have a local copy of mathjax.  You could get it with")
        print(
            "wget https://github.com/mathjax/MathJax/archive/"
            + "refs/tags/3.1.2.zip"
        )
        print("and then unzip")
    current_dir = os.getcwd()
    localfiles = {}
    for k in ["csl", "bib"]:
        localfiles[k] = [
            f for f in os.listdir(current_dir) if f.endswith("." + k)
        ]
        if len(localfiles[k]) == 1:
            localfiles[k] = localfiles[k][0]
        else:
            raise ValueError(
                f"You have more than one (or no) {k} file in this directory!"
                " Get rid of all but one! of " + "and".join(localfiles[k])
            )
    command = [
        "pandoc",
        "--bibliography",
        localfiles["bib"],
        f"--csl={localfiles['csl']}",
        "--filter",
        "pandoc-crossref",
        "--citeproc",
        "--mathjax",
        "--number-sections",
        "--toc",
        "-s",
        "-o",
        html_file,
        filename,
    ]
    # command = ['pandoc', '-s', '--mathjax', '-o', html_file, filename]
    print("running:", " ".join(command))
    subprocess.run(
        command,
    )
    print("running:\n", command)
    if has_local_jax:
        # {{{ for slow internet connection, remove remote files
        with open(html_file, encoding="utf-8") as fp:
            text = fp.read()
        patterns = [
            r"<script.{0,20}?cdn\.jsdeli.{0,20}?mathjax.{0,60}?script>",
            r"<script.{0,20}?https...polyfill.{0,60}?script>",
        ]
        for j in patterns:
            text = re.sub(j, "", text, flags=re.DOTALL)
        with open(html_file, "w", encoding="utf-8") as fp:
            fp.write(text)
        # }}}
    return


class Handler(FileSystemEventHandler):
    def __init__(self, filename, observer):
        self.observer = observer
        self.filename = filename
        self.html_file = filename.rsplit(".", 1)[0] + ".html"
        self.init_firefox()

    def init_firefox(self):
        self.firefox = webdriver.Chrome()
        run_pandoc(self.filename, self.html_file)
        if not os.path.exists(self.html_file):
            print("html doesn't exist")
        self.append_autorefresh()
        self.firefox.get("file://" + os.path.abspath(self.html_file))

    def on_modified(self, event):
        if os.path.normpath(
            os.path.abspath(event.src_path)
        ) == os.path.normpath(os.path.abspath(self.filename)):
            run_pandoc(self.filename, self.html_file)
            self.append_autorefresh()
            try:
                self.firefox.refresh()
            except selenium.common.exceptions.WebDriverException:
                print(
                    "I'm quitting!! You probably suspended the computer, which"
                    " seems to freak selenium out.  Just restart"
                )
                self.firefox.quit()
                self.init_firefox()

    def append_autorefresh(self):
        with open(self.html_file, "r", encoding="utf-8") as fp:
            all_data = fp.read()
        all_data = all_data.replace(
            "</head>",
            """
    <script id="MathJax-script" async src="MathJax-3.1.2/es5/tex-mml-chtml.js"\
></script>
    <script>
        // When the page is about to be unloaded, save the current scroll\
position
        window.addEventListener('beforeunload', function() {
            sessionStorage.setItem('scrollPosition', window.scrollY);
        });

        // When the page has loaded, scroll to the previous scroll position
        window.addEventListener('load', function() {
            var scrollPosition = sessionStorage.getItem('scrollPosition');
            if (scrollPosition) {
                window.scrollTo(0, scrollPosition);
                sessionStorage.removeItem('scrollPosition');
            }
        });
    </script>
</head>
    """,
        )
        with open(self.html_file, "w", encoding="utf-8") as fp:
            fp.write(all_data)


def watch(filename):
    observer = Observer()
    event_handler = Handler(filename, observer)
    observer.schedule(event_handler, path=".", recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


@register_command(
    "continuous pandoc build.  Like latexmk, but for markdown!",
    help={"filename": "Markdown or TeX file to watch for changes"},
)
def cpb(filename):
    watch(filename)


if __name__ == "__main__":
    filename = sys.argv[1]
    watch(filename)
    # Open the HTML file in the default web browser
