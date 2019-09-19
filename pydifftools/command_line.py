import sys
from . import check_numbers,match_spaces,split_conflict,wrap_sentences
import os
import gzip
import time
import subprocess
import logging
import re
from nbformat import v3, v4
def errmsg():
    print(r"""arguments are:
    fs      :   smart latex forward-search
                currently this works specifically for sumatra pdf located
                at "C:\Program Files\SumatraPDF\SumatraPDF.exe",
                but can easily be adapted based on os, etc.
                Add the following line (or something like it) to your vimrc:
                map <c-F>s :cd %:h\|sil !pydifft fs %:p <c-r>=line(".")<cr><cr>
                it will map Cntrl-F s to a forward search.
    mknb    :   Make a notebook file from a python script, following certain rules.
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
    xx      :   Convert xml to xlsx""")
    exit()
_ROOT = os.path.abspath(os.path.dirname(__file__))
def get_data(path):
    "return vbs and js scripts saved as package data"
    return os.path.join(_ROOT, path)
def recursive_include_search(directory, basename, does_it_input):
    with open(os.path.join(directory,basename+'.tex'),'r') as fp:
        alltxt = fp.read()
    # we're only sensitive to the name of the file, not the directory that it's in
    pattern = re.compile(r'\n[^%]*\\(?:input|include)[{]((?:[^}]*/)?'+does_it_input+')[}]')
    for actual_name in pattern.findall(alltxt):
        print(basename+" directly includes "+does_it_input)
        return True,actual_name
    print("file %s didn't directly include '%s' -- I'm going to look for the files that it includes"%(basename, does_it_input))
    pattern = re.compile(r'\n[^%]*\\(?:input|include)[{]([^}]+)[}](.*)')
    for inputname,extra in pattern.findall(alltxt):
        if '\\input' in extra or '\\include' in extra:
            raise IOError("Don't put multiple include or input statements on one lien --> are you trying to make my life difficult!!!??? ")
        print("%s includes input file:"%basename,inputname)
        retval,actual_name = recursive_include_search(
                directory,
                os.path.normpath(inputname),
                does_it_input)
        if retval:
            return True, actual_name
    return False,''
def look_for_pdf(directory,origbasename):
    'look for pdf -- if found return tuple(True, the basename of the pdf, the basename of the tex) else return tuple(False, "", "")'
    found = False
    basename = ''
    actual_name = ''
    for fname in os.listdir(directory):
        if fname[-4:] == '.tex':
            basename = fname[:-4]
            print("found tex file",basename)
            if os.path.exists(os.path.join(directory,basename + '.pdf')):
                print("found matching tex/pdf pair",basename)
                retval, actual_name = recursive_include_search(directory, basename, origbasename)
                if retval:
                    return True,basename,actual_name
                if not found:
                    print("but it doesn't seem to include",origbasename)
                    print("about to check for other inputs")
    return found,basename,actual_name
def main():
    if len(sys.argv) == 1:
        errmsg()
    command = sys.argv[1]
    arguments = sys.argv[2:]
    if command == 'num':
        check_numbers.run(arguments)
    elif command == 'mknb':
        jupyter_magic_re = re.compile("^get_ipython\(\).magic\(u'(.*)'\)")
        jupyter_cellmagic_re = re.compile("^get_ipython\(\).run_cell_magic\(u'(.*)'\)")
        assert len(arguments) == 1,"mknb should only be called with one argument"
        assert arguments[0].endswith('.py'),"this is supposed to be called with a .py file argument! (arguments are %s)"%repr(arguments)
        with open(arguments[0]) as fpin:
            text = fpin.read().decode('utf8')
        text = text.split('\n')
        newtext = []
        last_had_hash = False
        last_had_code = False
        for thisline in text:
            if thisline.startswith('# coding: utf-8'):
                pass
            elif thisline.startswith('# In['):
                last_had_code = False
            elif thisline.startswith('# Out['):
                pass
            elif thisline.startswith('# '):
                if not last_had_hash:
                    newtext.append('# <markdowncell>')
                newtext.append(thisline)
                last_had_hash = True
                last_had_code = False
            else:
                if not last_had_code:
                    newtext.append('# <codecell>')
                m = jupyter_magic_re.match(thisline)
                if m:
                    thisline = '%'+m.groups()[0]
                else:
                    m = jupyter_cellmagic_re.match(thisline)
                    if m:
                        thisline = '%%'+m.groups()[0]
                newtext.append(thisline)
                last_had_hash = False
                last_had_code = True
        text = '\n'.join(newtext)

        text += """
# <markdowncell>
# If you can read this, reads_py() is no longer broken! 

        """

        nbook = v3.reads_py(text)

        nbook = v4.upgrade(nbook)  # Upgrade v3 to v4
        nbook.metadata.update({'kernelspec':{'name':"Python [Anaconda2]",
            'display_name':'Python [Anaconda2]',
            'language':'python'}})

        jsonform = v4.writes(nbook) + "\n"
        with open(arguments[0].replace('.py','.ipynb'), "w") as fpout:
            fpout.write(jsonform.encode('utf8'))
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
        logging.debug("arguments are",arguments)
        if len(arguments) == 1:
            wrap_sentences.run(arguments[0])
        elif len(arguments) == 2 and arguments[0] == '--cleanoo':
            wrap_sentences.run(arguments[1],stupid_strip = True)
            logging.debug("stripped stupid markup from LibreOffice")
        elif len(arguments) == 0:
            wrap_sentences.run(None) # assumes stdin
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
        time.sleep(0.3)
        cmd = ['gvim']
        cmd.append('--remote-send')
        cmd.append('":cd %:h\n"')
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
        print("local directory:",local_dir)
        for j in range(2):
            if arguments[0][-5:] == '.docx':
                print("the first argument has a docx extension, so I'm bypassing the pandoc step")
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
                print("about to run",' '.join(cmd))
                os.system(' '.join(cmd))
        cmd = ['start']
        cmd += [get_data('diff-doc.js')]
        print("word files are",word_files)
        if word_files[0].find("C:") > -1:
            cmd += [word_files[0]]
        else:
            cmd += [os.getcwd() + os.path.sep + word_files[0]]
        cmd += [os.getcwd() + os.path.sep + word_files[1]]
        print("about to run",' '.join(cmd))
        os.system(' '.join(cmd))
    elif command == 'fs':
        texfile,lineno = arguments
        texfile = os.path.normpath(os.path.abspath(texfile))
        directory, texfile = texfile.rsplit(os.path.sep,1)
        assert texfile[-4:] == '.tex','needs to be called .tex'
        origbasename = texfile[:-4]
        cmd = ['"C:\\Program Files\\SumatraPDF\\SumatraPDF.exe" -reuse-instance']
        if os.path.exists(os.path.join(directory,origbasename+'.pdf')):
            cmd.append(os.path.join(directory,origbasename+'.pdf'))
            tex_name=origbasename
        else:
            print("no pdf file for this guy, looking for one that has one")
            found,basename,tex_name = look_for_pdf(directory, origbasename)
            orig_directory = directory
            if not found:
                while os.path.sep in directory and directory.lower()[-1] != ':':
                    directory, _ = directory.rsplit(os.path.sep,1)
                    print("looking one directory up, in ",directory)
                    found,basename,tex_name = look_for_pdf(directory, origbasename)
                    if found: break
            if not found: raise IOError("This is not the PDF you are looking for!!!")
            print("result:",directory,origbasename,found,basename,tex_name)
            # file has been found, so add to the command
            cmd.append(os.path.join(directory,basename+'.pdf'))
        cmd.append('-forward-search')
        cmd.append(tex_name+'.tex')
        cmd.append('%s -fwdsearch-color ff0000'%lineno)
        print("changing to directory",directory)
        os.chdir(directory)
        print("about to execute:\n\t",' '.join(cmd))
        os.system(' '.join(cmd))
    elif command == 'xx':
        format_codes = {'csv':6, 'xlsx':51, 'xml':46} # determined by microsoft vbs
        cmd = ['start']
        cmd += [get_data('xml2xlsx.vbs')]
        first_ext = arguments[0].split('.')[-1]
        second_ext = arguments[1].split('.')[-1]
        for j in arguments[0:2]:
            if j.find("C:") > -1:
                cmd += [j]
            else:
                cmd += [os.getcwd() + os.path.sep + j]
        cmd += [str(format_codes[j]) for j in [first_ext, second_ext]]
        print("about to run",' '.join(cmd))
        os.system(' '.join(cmd))
    else:
        errmsg()
    return
