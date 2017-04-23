import sys
from . import check_numbers,match_spaces,split_conflict,wrap_sentences
import os
import gzip
import time
import subprocess
def errmsg():
    print r"""arguments are:
    num     :   check numbers in a latex catalog (e.g. of numbered notebook)
                of items of the form '\item[anything number.anything]'
    gensync :   use a compiled latex original (first arg) to generate a synctex
                file for a scanned document (second arg), e.g.  with
                handwritten markup
    wmatch  :   match whitespace
    gvr     :   git forward search, with arguments

                - file
                - line
    sc      :   split conflict
    wd      :   word diff
    wr      :   wrap with indented sentence format (for markdown or latex).
                Optional flag --cleanoo cleans latex exported from
                OpenOffice/LibreOffice
    xx      :   Convert xml to xlsx"""
    exit()
def main():
    if len(sys.argv) == 1:
        errmsg()
    command = sys.argv[1]
    arguments = sys.argv[2:]
    if command == 'num':
        check_numbers.run(arguments)
    elif command == 'gensync':
        with gzip.open(arguments[0].replace(
            '.pdf','.synctek.gz')) as fp:
            orig_synctex = fp.read()
            fp.close()
        # since the new synctex is in a new place, I need to tell it
        # how to get back to the original place
        relative_path = os.path.relpath(
                os.path.dir(arguments[0]),
                os.path.dir(arguments[1]))
        base_fname = arguments[0].replace('.pdf','')
        new_synctex = orig_synctex.replace(
                base_fname,
                relative_path + base_fname)
        new_synctex = orig_synctex
        with gzip.open(arguments[1].replace(
            '.pdf','.synctek.gz')) as fp:
            fp.write(new_synctex)
            fp.write(argument[1].replace())
            fp.close()
    elif command == 'wr':
        print "arguments are",arguments
        if len(arguments) == 1:
            wrap_sentences.run(arguments[0])
        elif len(arguments) == 2 and arguments[0] == '--cleanoo':
            wrap_sentences.run(arguments[1],stupid_strip = True)
            print "stripped stupid markup from LibreOffice"
        else:
            raise ValueError("I don't understand your arguments:"+repr(arguments))
    elif command == 'gvr':
        cmd = ['gvim']
        cmd.append('--remote-wait-silent')
        cmd.append('+'+arguments[1])
        cmd.append(arguments[0])
        subprocess.Popen(' '.join(cmd))# this is forked
        time.sleep(0.3)
        cmd = ['gvim']
        cmd.append('--remote-send')
        cmd.append('"zO"')
        subprocess.Popen(' '.join(cmd))
    elif command == 'wmatch':
        match_spaces.run(arguments)
    elif command == 'sc':
        split_conflict.run(arguments)
    elif command == 'wd':
        if arguments[0].find('Temp') > 0:
            #{{{ if it's a temporary file, I need to make a real copy to run pandoc on
            fp = open(arguments[0])
            contents = fp.read()
            fp.close()
            fp = open(arguments[1].replace('.md','_old.md'),'w')
            fp.write(contents)
            fp.close()
            arguments[0] = arguments[1].replace('.md','_old.md')
            #}}}
        word_files = [x.replace('.md','.docx') for x in arguments[:2]]
        local_dir = os.path.dirname(arguments[1])
        print "local directory:",local_dir
        for j in range(2):
            if arguments[0][-5:] == '.docx':
                print "the first argument has a docx extension, so I'm bypassing the pandoc step"
            else:
                cmd = ['pandoc']
                cmd += [arguments[j]]
                cmd += ['--csl=edited-pmid-format.csl']
                cmd += ['--bibliography library_abbrev_utf8.bib']
                cmd += ['-s --smart']
                if len(arguments) > 2:
                    if arguments[2][-5:] == '.docx':
                        cmd += ['--reference-docx='+arguments[2]]
                    else:
                        raise RuntimeError("if you pass three arguments to wd, then the third must be a template for the word document")
                elif os.path.isfile(local_dir + os.path.sep + "template.docx"):
                    # by default, use template.docx in the current directory
                    cmd += ['--reference-docx=' + local_dir + os.path.sep + "template.docx"]
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
    elif command == 'xx':
        format_codes = {'csv':6, 'xlsx':51, 'xml':46} # determined by microsoft vbs
        cmd = ['start']
        cmd += [os.path.expanduser('~/xml2xlsx.vbs')]
        first_ext = arguments[0].split('.')[-1]
        second_ext = arguments[1].split('.')[-1]
        for j in arguments[0:2]:
            if j.find("C:") > -1:
                cmd += [j]
            else:
                cmd += [os.getcwd() + os.path.sep + j]
        cmd += [str(format_codes[j]) for j in [first_ext, second_ext]]
        print "about to run",' '.join(cmd)
        os.system(' '.join(cmd))
    else:
        errmsg()
    return
