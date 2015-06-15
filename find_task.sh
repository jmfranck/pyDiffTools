#!/bin/sh
# find a task -- like <c-g>o in vim
<<<<<<< HEAD
#grep -e "\\label{<c-r>r}" -rl inprocess/ *.tex<cr>:'a+1,'b-1 g/\.svn/d<cr>:'a+1,'b-1 g/\(^\\|\/\)\.[^\/]*\.swp/d<cr>
grep -e "\\label{sec:task$1}" -rl inprocess/ *.tex | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "c:\Program Files (x86)\Vim\vim74\gvim" -c 'exec("normal /\\\\label{sec:task'$1'}\nzOmT")' @ 
=======
if [ "$2" = "l" ] ; then
    grep list* -rle "\\\\item\[.*\<$1\." | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "/c/Program Files/vim72/vim72/gvim.exe" -c 'exec("normal /\\\\item\\[.*\\<'$1'/e\nzO")' @
else
    grep inprocess/ *.tex -rle "\\label{sec:task$1}" | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "/c/Program Files/vim72/vim72/gvim.exe" -c
    'exec("normal /\\\\label{sec:task'$1'}\nzO")' @
fi
>>>>>>> c600fae83b1e7911c76be995619e6ea1e45fe5a0
