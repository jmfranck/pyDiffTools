import sys
from . import check_numbers,match_spaces,split_conflict
def errmsg():
    print """arguments are:
    num    (check numbers)
    wmatch (match whitespace)
    sc     (split conflict)"""
    return
def main():
    if len(sys.argv) == 1:
        errmsg()
    command = sys.argv[1]
    arguments = sys.argv[2:]
    if command == 'num':
        check_numbers.run(arguments)
    elif command == 'wmatch':
        match_spaces.run(arguments)
    elif command == 'sc':
        split_conflict.run(arguments)
    return
