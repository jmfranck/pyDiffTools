#!/bin/sh

# diff is called by git with 7 parameters:
# path old-file old-hex old-mode new-file new-hex new-mode
gvimcmd="gvim"

if [ "$#" == "0" ]; then
	git status -s | sed "/^[^U]/d"
else
    if ! [ -e $1.merge_head ]; then
        pydifft sc $1
    fi
	$gvimcmd -d $1.merge_head $1.merge_new
fi
