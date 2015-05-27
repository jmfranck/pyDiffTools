#!/bin/sh

# diff is called by git with 7 parameters:
# path old-file old-hex old-mode new-file new-hex new-mode

if [ "$#" == "0" ]; then
	git status -s | sed "/^[^U]/d"
else
    if ! [ -e $1.merge_head ]; then
        python ~/notebook/split_conflict.py $1
    fi
	"/c/Program Files (x86)/Vim/vim74/gvim" -d $1.merge_head $1.merge_new
fi
