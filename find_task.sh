#!/bin/sh
# find a task -- like <c-g>o in vim
vimlocation="/c/Program Files/vim72/vim72/gvim.exe"
if [ "$1" = "-l" ] ; then
    if [ `echo $2 |sed -n '/^[0-9]\+$/p'` ] ; then
        echo "this is a number"
        grep list* -rle "\\\\item\[.*\<$2\." | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "$vimlocation" -c 'exec("normal /\\\\item\\[.*\\<'$2'\\./e\nzO")' @
    else
        echo "this is not a number"
        vimsearch='exec("normal /\\<'$2'\\>\nzO")'
        echo "I find the following files that match"
        echo `grep list* -rle "\<$2\>" | sed -n "/\.tex$/p"`
        echo "and I plan to run the following vim command $vimsearch"
        grep list* -rle "\<$2\>" | sed -n "/\.tex$/p" | xargs -i@ "$vimlocation" -c "$vimsearch" @ # apparently the quotes are required to expand the $vimsearch here -- this is equivalent to typing the lhs of the equation above here
    fi
else
    testresult=$(grep inprocess/ *.tex -rle "\\label{sec:task$1}" | sed "/\.swp$/d" | sed -n '/\.tex\|\.txt/p')
    if [ "$testresult" ] ; then
        echo "$testresult" | xargs -i@ "$vimlocation" -c 'exec("normal /\\\\label{sec:task'$1'}\nzO")' @
    else
        echo "I can't find $1 in the notebook"
    fi
fi
