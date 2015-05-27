#!/bin/sh

# diff is called by git with 7 parameters:
# path old-file old-hex old-mode new-file new-hex new-mode

if [ "$#" == "0" ]; then
	git status -s | sed "/^[^U]/d"
else
	rm $1.merge_head
    cat $1.merge_new | sed "/^#%%%%%BRANCH TITLE/d" > $1
    rm $1.merge_new
    git add $1
    echo "WARNING!!! there is a problem with resolve_markedone!"
fi
