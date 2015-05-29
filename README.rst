==================================================
        pyDiffTools
==================================================
:Author: <http://github.com/jmfranck> 
.. _vim: http://www.vim.org

This is a set of tools to help with merging, mostly for use with vim_.

At this stage, it's a very basic and development-stage repository.
The scripts are accessed with the command ``pydifft``

Included are:
- A very basic merge tool that takes a conflicted file and generates a .merge_head and .merge_new file.
    - you can leave the files saved and come back to a complicated merge later
    - less complex than the gvimdiff merge tool used with git.
    - works with "onewordify," below
- A script that matches whitespace between two text files.
    - pandoc can convert between markdown/latex/word, but doing this messes with your whitespace and gvimdiff comparisons.
    - This allows you to use an original file with good whitespace formatting as a "template" that you can match other (e.g. pandoc converted file) onto another
- A script that searches a notebook for numbered tasks, and sees whether or not they match (this is for organizing a lab notebook, to be described)

