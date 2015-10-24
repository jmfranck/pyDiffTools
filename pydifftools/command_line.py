import sys
from . import check_numbers,match_spaces,split_conflict
import os
def errmsg():
    print """arguments are:
    num    (check numbers)
    wmatch (match whitespace)
    sc     (split conflict)
    wd     (word diff)"""
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
    elif command == 'wd':
        word_files = [x.replace('.md','.docx') for x in arguments[:2]]
        for j in range(2):
            cmd = ['pandoc']
            cmd += [arguments[j]]
            cmd += ['-s --smart']
            if not arguments[0][-5:] == '.docx': # so that I can pass docx arguments
                if len(arguments) > 2:
                    if arguments[2][-5:] == '.docx':
                        cmd += ['--reference-docx='+arguments[2]]
                    else:
                        raise RuntimeError("if you pass three arguments to wd, then the third must be a template for the word document")
                elif os.path.isfile("template.docx"):
                    # by default, use template.docx in the current directory
                    cmd += ['--reference-docx=template.docx']
                cmd += ['-o']
                cmd += [word_files[j]]
                print "about to run",' '.join(cmd)
                os.system(' '.join(cmd))
        cmd = ['start']
        cmd += [os.path.expanduser('~/diff-doc.js')]
        print "word files are",word_files
        if word_files[0].find("C:") > -1:
            cmd += [word_files[0]]
        else:
            cmd += [os.getcwd() + os.path.sep + word_files[0]]
        cmd += [os.getcwd() + os.path.sep + word_files[1]]
        print "about to run",' '.join(cmd)
        os.system(' '.join(cmd))
    else:
        errmsg()
    return
