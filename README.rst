==================================================
        pydifftools
==================================================
:Info: See <https://github.com/jmfranck/pyDiffTools>
:Author: J. M. Franck <https://github.com/jmfranck>
.. _vim: http://www.vim.org

this is a set of tools to help with merging, mostly for use with vim_.

at this stage, it's a very basic and development-stage repository.
the scripts are accessed with the command ``pydifft``

included are:

- a very basic merge tool that takes a conflicted file and generates a .merge_head and .merge_new file.

- you can leave the files saved and come back to a complicated merge later

    * less complex than the gvimdiff merge tool used with git.

    * works with "onewordify," below

- a script that matches whitespace between two text files.

    * pandoc can convert between markdown/latex/word, but doing this messes with your whitespace and gvimdiff comparisons.

    * this allows you to use an original file with good whitespace formatting as a "template" that you can match other (e.g. pandoc converted file) onto another

- a script that searches a notebook for numbered tasks, and sees whether or not they match (this is for organizing a lab notebook, to be described)

Future versions will include:

- Scripts for converting word html comments to latex commands.

- converting one word per line (for doing things like wdiff, but with more control)
