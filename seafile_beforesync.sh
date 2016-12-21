#!/usr/bin/bash
echo "if you think the files from seafile are newer, then delete the corresponding SFConflict file before running this"
ls *SFConflict* | sed 's/\(.*\)\( (SFConflict.*)\)\.\([a-z_]\+\)/mv "\1\2.\3" \1.\3/' > temp.sh
echo """
echo "after running this, check and run temp.sh to restore to the files that were in use on this computer"
