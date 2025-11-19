pydifftools
===========

:Info: See <https://github.com/jmfranck/pyDiffTools>
:Author: J. M. Franck <https://github.com/jmfranck>

.. _vim: http://www.vim.org

this is a set of tools to help with merging, mostly for use with vim_.

The scripts are accessed with the command ``pydifft``

included are (listed in order of fun/utility):

- `pydifft cpb <filename.md>` ("continuous pandoc build")
  This continuously monitors
  `filename.md`, build the result,
  and displays it in your browser. 

  Continuous pandoc build.
  This works *very well* together
  with the `g/` vim command
  (supplied by our standard vimrc
  gist) to search for phrases (for
  example `g/ n sp me` to find "new
  spectroscopic methodology" -- this
  works *much better* than you
  would expect)

  For this to work, you need to
  **install selenium with** `pip
  install selenium` *not conda*.
  Then go to `the selenium page <https://pypi.org/project/selenium/>`_
  and download the chrome driver.
  Note that from there, it can be hard to find the
  chrome driver -- as of this update,
  the drivers are `here <https://googlechromelabs.github.io/chrome-for-testing/#stable>`_,
  but it seems like google is moving them around.
  You also need to install `pandoc <https://pandoc.org/installing.html>`_
  as well as `pandoc-crossref <https://github.com/lierdakil/pandoc-crossref>`_
  (currently tested on windows with *version 3.5* of the former,
  *not the latest installer*,
  since crossref isn't built with the most recent version).
- `pydifft wgrph <graph.yaml>` watches a YAML flowchart description,
  rebuilds the DOT/SVG output using GraphViz, and keeps a browser window
  refreshed as you edit the file.  This wraps the former
  ``flowchart/watch_graph.py`` script so all of its functionality is now
  available through the main ``pydifft`` entry point.
- `pydifft tex2qmd file.tex` converts LaTeX sources to Quarto markdown.
  The converter preserves custom observation blocks and errata tags while
  translating verbatim/python environments into fenced code blocks so the
  result is ready for the Pandoc-based builder.
- `pydifft qmdb [--watch] [--no-browser] [--webtex]` runs the relocated
  ``fast_build.py`` logic from inside the package.  Without ``--watch`` it
  performs a single build of the configured `_quarto.yml` targets into the
  ``_build``/``_display`` directories; with ``--watch`` it starts the HTTP
  server and automatically rebuilds the staged fragments whenever you edit
  a ``.qmd`` file.
- `pydifft qmdinit [directory]` scaffolds a new Quarto-style project using
  the bundled templates and example ``project1`` hierarchy, then downloads
  MathJax into ``_template/mathjax`` so the builder can run immediately.
  This is analogous to ``git init`` for markdown notebooks.
- `pydifft wr <filename.tex|md>` (wrap)
  This provides a standardized (and
  short) line
  wrapping, ideal for when you are
  working on manuscripts that you
  are version tracking with git.
- `pydifft wmatch` ("whitespace match"): a script that matches whitespace between two text files.

    * pandoc can convert between markdown/latex/word, but doing this messes with your whitespace and gvimdiff comparisons.

    * this allows you to use an original file with good whitespace formatting as a "template" that you can match other (e.g. pandoc converted file) onto another

- `pydifft wd` ("word diff"): generate "track changes" word files starting from pandoc markdown in a git history.  Assuming that you have copied diff-doc.js (copied + licensed from elsewhere) into your home directory, this will use pandoc to convert the markdown files to MS Word, then use the MS Word comparison tool to generate a document where all relevant changes are shown with "track changes."

    * by default, this uses the file `template.docx` in the current directory as a pandoc word template

- `pydifft sc` ("split conflicts"): a very basic merge tool that takes a conflicted file and generates a .merge_head and .merge_new file, where basic 

    * you can use this directly with gvimdiff, you can use the files in a standard gvimdiff merge

        * unlike the standard merge tool, it will 

    * less complex than the gvimdiff merge tool used with git.

    * works with "onewordify," below


- a script that searches a notebook for numbered tasks, and sees whether or not they match (this is for organizing a lab notebook, to be described)

Future versions will include:

- Scripts for converting word html comments to latex commands.

- converting to/form one word per line files (for doing things like wdiff, but with more control)
