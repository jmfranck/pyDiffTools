#!/bin/sh
# find a task -- like <c-g>o in vim
if [ "$2" = "l" ] ; then
    grep list* -rle "\\\\item\[.*\<$1\." | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "/c/Program Files/vim72/vim72/gvim.exe" -c 'exec("normal /\\\\item\\[.*\\<'$1'/e\nzO")' @
else
    grep inprocess/ *.tex -rle "\\label{sec:task$1}" | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "/c/Program Files/vim72/vim72/gvim.exe" -c
    'exec("normal /\\\\label{sec:task'$1'}\nzO")' @
fi
