#!/bin/sh
# find a task -- like <c-g>o in vim
#grep -e "\\label{<c-r>r}" -rl inprocess/ *.tex<cr>:'a+1,'b-1 g/\.svn/d<cr>:'a+1,'b-1 g/\(^\\|\/\)\.[^\/]*\.swp/d<cr>
grep -e "\\label{sec:task$1}" -rl inprocess/ *.tex | sed "/\.svn$/d" | sed "/\.swp$/d" | xargs -i@ "c:\Program Files (x86)\Vim\vim74\gvim" -c 'exec("normal /\\\\label{sec:task'$1'}\nzOmT")' @ 
