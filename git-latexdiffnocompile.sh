#!/bin/bash
#TMPDIR=$(mktemp -d /tmp/git-latexdiff.XXXXXX)
#latexdiff "$1" "$2" > $TMPDIR/diff.tex
# in the following, adding "caption" as a "textcmd" makes markup inside it possible, while "safecmd" marks mbox as something it can include in the markup
#echo 'current directory'`pwd`
#latexdiff -p mylatexdiff-preamble.sty --append-textcmd "caption,intertext,ubpair,obpair,paragraph,textbf,textit,johnmark" --append-safecmd "widetilde,mbox,Big,big,frac,_,gamma,tau,xi" --exclude-safecmd "johnmark" "$1" "$2" | sed "s/%DIF > REMOVE //" | sed "s/%REMOVE //" | sed "s/\r//g" > XXXtemp_diff.tex
echo "trying to diff $1 to $2"
echo "as a check, ls them"
ls -l $1
ls -l $2
#cp $1 XXXtemp_fordiff.tex
latexdiff -p mylatexdiff-preamble.sty --append-textcmd "caption,intertext,ubpair,obpair,paragraph,textbf,textit,section,subsection,subsubsection" --exclude-textcmd "john,bibcite" --append-safecmd "mbox,Big,big,frac,_,gamma,correltime,tau,xi,section,subsection,subsubsection" --exclude-safecmd "bibcite" "$1" "$2" | sed "s/%DIF > REMOVE //" | sed "s/%REMOVE //"| sed 's/\(\\john\[[^]]*\)\(\\DIF\)/\1\\protect\2/g' | sed "s/\r//g" > XXXtemp_diff.tex
#myname=`basename $2 .tex`
#myname=$myname'_diff.tex'
echo "sending output to" `echo $2|sed 's/\.tex/_diff.tex/g'`
mv XXXtemp_diff.tex `echo $2|sed 's/\.tex/_diff.tex/g'`
