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

  ``cpb`` manages ``comment_tags.lua``, the comment stylesheets and
  ``comment_toggle.js`` beside the Markdown source. A packaged SHA-256
  catalog covers current and historical helpers from Git, including the
  normal, margin and no-comment Lua variants. Known older files trigger an
  update offer; unrecognized files are treated as possible local edits.
  Updating removes generated helpers from Git tracking without deleting
  the working copies, and adds them to ``.gitignore``. Keeping local edits
  or Git tracking requires a second confirmation. An ignored
  ``.pydifft-comment-filter.json`` records the approved file hashes; changing
  any helper causes another prompt. Keeping known older versions applies
  only to the current ``cpb`` session.

  ``--no-comments`` selects the no-comment Lua variant. Running without
  that flag when the on-disk Lua matches a current or historical no-comment
  version asks whether to show comments. The selection uses the files'
  contents, without active/inactive swapping or remembered mode settings.
  Existing ``.inactive`` copies are migrated, preserving unique local
  edits in ignored recovery files. Maintainers refresh the catalog with
  ``python .github/scripts/update_comment_filter_history.py``; the release
  workflow also refreshes it before building distributions.

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
  reference) to open a URL comparing against that Git snapshot.
  Additions are green, deletions are red and struck through, and
  unchanged content is muted. Renames share one box; date, status, and
  dependency changes are annotated. Navigation, filters, and reloads retain
  the baseline through the ``diff-base`` URL parameter, whose reference and
  commit appear below the graph. All view choices come from the URL:
  ``t`` focuses a task and its ancestors, ``d=1``
  orders dated tasks, and ``p=1`` excludes completed tasks. Command options
  choose the initial URL. Removing ``diff-base`` restores normal rendering;
  clearing the entire query shows the full plan, including completed and
  undated tasks. Each embedded SVG and live refresh uses the same URL mode.
  The search button beside Home and Zoom finds text in the visible graph,
  highlights matches, and centers the containing task at your chosen zoom.
  Tab or Enter advances to the next match; Shift+Tab or Shift+Enter goes
  back. Esc closes search. Phrases can span wrapped lines and formatted
  text. Resizing the window scales the current view with the viewport.
  The ``1:1`` button displays fonts at their declared pixel sizes, including
  correction for GraphViz's SVG scaling. Right-click a task and select
  Jump to source to open its YAML definition in gvim.
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
  Run ``pydifft --add_to_git tree`` to add the matching ``git tree`` alias.
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
  Run ``pydifft --add_to_git gd`` to install the global ``git gd`` alias,
  retaining the exact command of an existing global ``gd`` alias. If none
  is configured, it installs ``!f() { pydifft gd "$@"; }; f``.
  Configure ``difftool.mygvim.cmd`` for the GUI diff tool.
- ``pydifft --add_to_git gd pd tree mergein`` installs any selected subset
  of these global Git aliases in one invocation. Installation appears
  alongside the subcommands in root help; the former per-command
  ``--install`` and ``--add-to-git`` flags have been removed.
- ``pydifft mergein BRANCH [--remote REMOTE]`` updates an incoming local
  branch without switching branches, then merges it into the current
  branch. Install ``git mergein`` with ``pydifft --add_to_git mergein``.
  ``git mergein incoming/topic`` runs ``git fetch origin
  incoming/topic:incoming/topic`` followed by ``git merge --no-ff
  incoming/topic``. Use ``--remote upstream`` to select another remote;
  ``origin`` is the default. Fetch failures stop the sequence, local
  branch updates are not forced, and merge conflicts remain available
  for normal Git resolution.

  Installing ``mergein`` also installs its Bash completion in the user
  Bash completion directory (honoring ``BASH_COMPLETION_USER_DIR`` and
  ``XDG_DATA_HOME``). With standard Git Bash completion enabled,
  ``git mergein`` suggests cached branches of the selected remote, using
  bare branch names such as ``incoming/topic``. Completion does not
  contact the remote; fetch to refresh the suggestions. The ``pydifft``
  form supports the same suggestions when argcomplete is enabled.
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

    * ``cpb`` and ``wmatch`` share a matcher that finds changed hunks, aligns
      their words using Git's minimal diff, and restores reference whitespace.
      It then considers extra breaks that preserve an unchanged reference line
      without stranding a tiny edited fragment, and checks wrapping rules.

    * ``--wrapnumber`` sets the maximum width (79 for ``cpb`` and ``wmatch``).
      Wmatch also uses nearby reference widths for large edits, retaining
      unchanged reference lines and protected Markdown blocks.

    * ``--trailing-dependent-phrase`` defaults to 20: a clause boundary within
      20 characters of the maximum width must end the line, even when its
      trailing phrase would still fit. Commas, semicolons, colons, parentheses,
      dashes, and inline-math boundaries are supported. Set it to 0 to disable
      this rule. The option is shared by ``cpb``, ``wmatch``, ``wr`` and
      ``wrchk``; ``--punctuation-slop`` remains an alias.

- ``pydifft pd OLD NEW [--no-compile]`` ("PDF diff") compares two ``.md``
  files or two ``.tex`` files. It writes ``NEW_diff.tex`` beside the newer
  input and, by default, compiles ``NEW_diff.pdf`` there with ``pdflatex``.
  For example, ``pydifft pd old.md paper.md`` produces ``paper_diff.tex``
  and ``paper_diff.pdf``. ``--no-compile`` retains the diff TeX without
  running a compiler and supports TeX fragments as well as full documents.

  Both formats use ``mylatexdiff-preamble.sty`` and the existing custom
  ``latexdiff`` options and postprocessing. The preamble is searched for
  in the current directory, beside NEW, then through ``kpsewhich``.
  Tools must be available on the caller's PATH, including any TeX Live
  directory configured in your shell. Markdown additionally requires
  Pandoc and pandoc-crossref; conversion honors declared bibliography and
  CSL metadata, renders citations and cross-references, and resolves local
  images beside each source. Converted TeX intermediates are temporary;
  the Markdown sources are unchanged.

  Markdown code blocks retain Pandoc syntax highlighting. Changed lines
  get a colored background and a ``+`` or ``-`` marker, with each line
  processed independently so highlighted code remains valid TeX.
  Prose keeps the custom preamble styling.

  Python runs ``pdflatex`` beside NEW until references and the table of
  contents settle (at most six passes), running ``bibtex`` or ``biber``
  when required. ``latexmk`` and its configuration are not used.
  Compilation artifacts and the diff TeX remain available if compilation
  fails. Existing generated outputs can be replaced on a successful rerun.
  The former ``git-latexdiffnocompile.sh`` is a compatibility wrapper for
  ``pydifft pd --no-compile``.

  Run ``pydifft --add_to_git pd`` to install the global ``git pd`` alias.
  It accepts Git diff arguments: ``git pd 00ffaa -- filename.md`` compares
  that revision with the working file; bare ``git pd`` compares unstaged
  changes; ``git pd --cached`` compares staged changes; and
  ``git pd OLD NEW -- filename.md`` compares two revisions. Ranges and
  Git pathspecs work as usual, including from repository subdirectories.
  Each changed Markdown or TeX file produces its own ``NAME_diff.tex`` and
  PDF beside the document's working-tree path. ``git pd --no-compile``
  generates only TeX. Other file types are skipped, and unchanged files
  produce no output. Additions, deletions, and renames are supported;
  unresolved merge conflicts must be resolved first. Historical document
  snapshots use the current project's bibliography, images, and TeX
  includes. The shared installer edits only the requested global Git alias.

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
