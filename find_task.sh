#!/bin/sh
# find a task -- like <c-g>o in vim
vimlocation="/c/Program Files/vim72/vim72/gvim.exe"
cd ~/notebook

# process arguments -- modified from http://stackoverflow.com/questions/192249/how-do-i-parse-command-line-arguments-in-bash
find_mode="vim"
while [ $# -gt 1 ]
do
key="$1"

    case $key in
        -l|--listnum)
            find_mode="list"
            shift # $2 --> $1, $3 --> $2, etc.
        ;;
        -p|--print)
            find_mode="print"
            shift # past argument
        ;;
        *)
            echo "I don't know what $key is supposed to do!"
            exit 1 # unknown option
        ;;
    esac
done
input_str="$1"

if [ "$find_mode" = "list" ] ; then
    if [ `echo $input_str |sed -n '/^[0-9]\+$/p'` ] ; then
        echo "this is a number"
        gvim -t "lst:$input_str" &
    else
        echo "this is not a number"
        vimsearch='exec("normal /\\c\\<'$input_str'\\>\nzO")'
        echo "I find the following files that match"
        echo `grep list* -rile "\<$input_str\>" | sed -n "/\.tex$/p"`
        echo "and I plan to run the following vim command $vimsearch"
        grep list* -rile "\<$input_str\>" | sed -n "/\.tex$/p" | xargs -n 1 -P 5 -i@ "$vimlocation" -c "$vimsearch" @ # apparently the quotes are required to expand the $vimsearch here -- this is equivalent to typing the lhs of the equation above here
    fi
else
    if [ "$find_mode" = "vim" ]; then
        if [ `echo $input_str |sed -n '/^[0-9]\+$/p'` ] ; then
            echo "this is a number"
            gvim -t "sec:task$input_str" &
        else
            echo "$testresult" | xargs -n 1 -P 5 -i@ "$vimlocation" -c 'exec("normal /\\\\label{sec:task'$input_str'}\nzO")' @
        fi
    elif [ "$find_mode" = "print" ]; then
        testresult=$(grep inprocess/ *.tex -rle "\\label{sec:task$input_str}" | sed "/\.swp$/d" | sed -n '/\.tex\|\.txt/p')
        if [ "$testresult" ] ; then
            echo "$testresult"
        else
            echo "I can't find $input_str in the notebook"
        fi
    else
        echo "I can't find $input_str in the notebook"
    fi
fi
