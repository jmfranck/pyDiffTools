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

- `pydifft sc` ("split conflicts"): a very basic merge tool that takes a conflicted file and generates a .merge_head and .merge_new file, where basic 

    * you can use this directly with gvimdiff, you can use the files in a standard gvimdiff merge

        * unlike the standard merge tool, it will 

    * less complex than the gvimdiff merge tool used with git.

    * works with "onewordify," below

- `pydifft wmatch` ("whitespace match"): a script that matches whitespace between two text files.

    * pandoc can convert between markdown/latex/word, but doing this messes with your whitespace and gvimdiff comparisons.

    * this allows you to use an original file with good whitespace formatting as a "template" that you can match other (e.g. pandoc converted file) onto another

- `pydifft wd` ("word diff"): generate "track changes" word files starting from pandoc markdown in a git history.  Assuming that you have copied diff-doc.js (copied + licensed from elsewhere) into your home directory, this will use pandoc to convert the markdown files to MS Word, then use the MS Word comparison tool to generate a document where all relevant changes are shown with "track changes."

    * by default, this uses the file `template.docx` in the current directory as a pandoc word template

- a script that searches a notebook for numbered tasks, and sees whether or not they match (this is for organizing a lab notebook, to be described)

Future versions will include:

- Scripts for converting word html comments to latex commands.

- converting to/form one word per line files (for doing things like wdiff, but with more control)
