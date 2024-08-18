"""
this requires geckodriver to be installed and available
"""

import time
from selenium import webdriver
import subprocess
import sys
import os
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def run_pandoc(filename, html_file):
    command = [
        "pandoc",
        "--bibliography",
        "references.bib",
        "--csl=superscript_ref_short.csl",
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
    subprocess.run(command)
    return


class Handler(FileSystemEventHandler):
    def __init__(self, filename):
        self.filename = filename
        self.html_file = filename.rsplit(".", 1)[0] + ".html"
        # self.firefox = webbrowser.get('firefox')
        # self.firefox = webdriver.Firefox() # requires geckodriver
        self.firefox = webdriver.Chrome()  # requires chromium
        run_pandoc(self.filename, self.html_file)
        self.append_autorefresh()
        # self.firefox.open_new_tab(self.html_file)
        self.firefox.get("file://" + os.path.abspath(self.html_file))

    def on_modified(self, event):
        # print("modification event")
        if os.path.normpath(
            os.path.abspath(event.src_path)
        ) == os.path.normpath(os.path.abspath(self.filename)):
            print("about to run pandoc")
            run_pandoc(self.filename, self.html_file)
            self.append_autorefresh()
            try:
                self.firefox.refresh()
            except selenium.common.exceptions.WebDriverException:
                print("I'm quitting!! You probably suspended the computer, which seems to freak selenium out.  Just restart")
                sys.exit(1)
            print("and refreshed!")
        else:
            # print("saw a change in",os.path.normpath(os.path.abspath(event.src_path)))
            # print("not",os.path.normpath(os.path.abspath(self.filename)))
            pass

    def append_autorefresh(self):
        print("about to add scripts")
        with open(self.html_file, "r") as fp:
            all_data = fp.read()
        all_data = all_data.replace(
            "</head>",
            """
    <script id="MathJax-script" async src="MathJax-3.1.2/es5/tex-mml-chtml.js"></script>
    <script>
        // When the page is about to be unloaded, save the current scroll position
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
        with open(self.html_file, "w") as fp:
            fp.write(all_data)
        # print("done adding")


def watch(filename):
    event_handler = Handler(filename)
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
    # print("returning from watch")


if __name__ == "__main__":
    filename = sys.argv[1]
    watch(filename)
    # Open the HTML file in the default web browser
