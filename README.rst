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

  When Pandoc reports missing citations, ``cpb`` retrieves their BibTeX
  entries from the running local Zotero application, updates the active
  bibliography, and rebuilds once. Install and enable
  `Better BibTeX <https://retorque.re/zotero-better-bibtex/installation/>`_
  in Zotero. No API key or Python dependency is needed. The integration uses
  Better BibTeX's documented
  `local JSON-RPC API <https://retorque.re/zotero-better-bibtex/exporting/json-rpc/>`_
  at ``127.0.0.1:23119`` and searches the default personal library.
  Zotero supports Windows, macOS, and Linux; this integration uses portable
  Python file operations and Qt dialogs. Its automated runtime checks have
  been performed on Linux, not on Windows.

  Comment bubbles use author tags such as ``<JFcom>…</JFcom>`` and
  ``<JFcom-left>…</JFcom-left>``. Block comments can use Markdown Div classes
  such as ``::: {.JFcom-left}``. Add a quoted six-digit hex color to the YAML
  header (for example, ``JFcolor: '#5aa0ff'``) to enable that author's tags.
  Before the first build, ``cpb`` offers to migrate legacy ``<comment>`` tags
  and ``.comment-left/right`` blocks, and resolves author tags without a
  matching color. New authors choose a hue in a Qt picker; ``cpb`` adds their
  ``XXcolor`` field to the header.

  Declare a single local ``.bib`` file with ``bibliography: references.bib``
  in the Markdown YAML header; relative paths are resolved beside the
  Markdown file. Without that declaration, ``cpb`` uses a single adjacent
  ``.bib`` file. Multiple or unsupported bibliographies are rendered normally
  but are not automatically edited. Missing keys, unavailable Zotero, and
  failed updates produce warnings; rendering continues. If Zotero or Better
  BibTeX is unavailable at startup, an informational Qt window explains the
  feature without blocking the preview.

  Before importing a possible duplicate, a Qt dialog offers keeping the
  existing entry, keeping the Zotero entry, or merging selected fields.
  Matching uses DOI, book ISBN/edition, or a similar title with the same
  first author and year. Conflicting DOIs are not treated as duplicates.
  This follows the identifier and field comparison approach used by
  `JabRef <https://docs.jabref.org/finding-sorting-and-cleaning-entries/mergeentries>`_.
  The merge defaults to existing values and the existing key, filling absent
  fields from Zotero. You can also keep both entries or skip an import.
  After resolving a duplicate, ``@UNCHOSEN`` becomes ``@CHOSEN`` in the active
  Markdown document. Code, links, ordinary text, and other documents are not
  rewritten. Untouched bibliography entries retain their original text.
  Edits made while a lookup or dialog is in progress abort the update.

  Tests use recorded Zotero responses and real Pandoc. For the optional local
  smoke tests, run ``PYDIFFTOOLS_ZOTERO_LIVE=1 python -m pytest -q
  tests/test_zotero.py``. This additionally checks the live Hoult export and
  builds a temporary copy of ``~/notebook/papers/eigenmode``, verifying that
  the original files are unchanged. The ordinary suite requires neither
  Zotero nor this notebook directory.
- `pydifft wgrph <graph.yaml>` watches a YAML flowchart description,
  rebuilds the DOT/SVG output using GraphViz, and keeps a browser window
  refreshed as you edit the file.  This wraps the former
  ``flowchart/watch_graph.py`` script so all of its functionality is now
  available through the main ``pydifft`` entry point.
  Add ``--diff-base HEAD`` (or a branch, tag, commit, or quoted reflog
  reference) to compare against that Git snapshot throughout the preview
  session. Additions are green, deletions are red and struck through, and
  unchanged content is muted. Renames share one box; date, status, and
  dependency changes are annotated. Navigation, filters, and reloads retain
  the baseline, whose reference and commit appear below the graph.
  Comparison uses the same repository-relative YAML path; a file absent
  from the revision is treated as an empty plan. Historical file renames
  are not followed, and comparison markup is never written to YAML.
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
- ``pydifft tree`` (or ``git tree`` with the alias installed) opens the last
  40 commits across all branches, in Git date order. Use the down arrow
  below the history to add the next 40 commits. Colors follow
  first-parent ancestry; merged branches join the receiving branch.
  Tags and branch tips have vector icon badges; hashes appear on hover.
  Click any part of a commit row
  to compare with the working directory, or right-click to copy its hash
  or set a commit as the comparison endpoint. The right-click menu can restore
  the working-directory endpoint. Diff window titles show the equivalent
  arguments, preferring tags, then branch names, then six-character hashes.
  Run ``pydifft tree --install`` to add the matching ``git tree`` alias.
- ``pydifft gd`` (or ``git gd`` with the alias installed) reviews unstaged
  changes, like bare ``git diff``.
  ``pydifft gd [git diff args...]`` shows the same Qt review table as the old
  ``git_gd_qt.py`` helper before launching ``git difftool`` for a selected
  file.
  Image rows are scored in the background and displayed as normalized
  ``rgb X.X a X.X`` RMS changes; RGB change orders the image rows as scores
  arrive.
  Raster images open in a Qt viewer that aligns the old and new image,
  displays their RGB difference, and uses up/down controls to switch
  among the original, difference, and aligned new image. Images with an
  alpha channel are displayed over a checkerboard; when transparency
  changes, an additional red/blue alpha-difference view is included.
  Run ``pydifft gd --install`` to add the matching ``git gd`` alias to
  your global git config.
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
  Headers, fenced code blocks, and Pandoc tables retain their formatting.
  Display-math delimiters get their own lines while equation contents retain
  their wrapping; inline-math boundaries are preferred places to wrap prose.
- `pydifft wmatch` ("whitespace match"): a script that matches whitespace between two text files.

    * pandoc can convert between markdown/latex/word, but doing this messes with your whitespace and gvimdiff comparisons.

    * this allows you to use an original file with good whitespace formatting as a "template" that you can match other (e.g. pandoc converted file) onto another

    * changed prose lines exceeding 1.5 times the nearby reference width are
      wrapped using the same sentence and punctuation rules as ``wr``.
      Existing surrounding line breaks are retained; the fallback width is
      80 columns when the reference provides too little prose.

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
