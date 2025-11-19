# PYTHON_ARGCOMPLETE_OK

import argparse
import sys
import os
import gzip
import time
import subprocess
import re
import nbformat
import difflib
import shutil
from pathlib import Path
from . import (
    match_spaces,
    split_conflict,
    outline,
)
from .continuous import cpb
from .wrap_sentences import wr as wrap_sentences_wr  # registers wrap command
from .separate_comments import tex_sepcomments
from .unseparate_comments import tex_unsepcomments
from .comment_functions import matchingbrackets
from .copy_files import copy_image_files
from .searchacro import replace_acros
from .rearrange_tex import run as rearrange_tex_run
from .flowchart.watch_graph import wgrph
from .notebook.tex_to_qmd import tex2qmd
from .notebook.fast_build import qmdb, qmdinit


from .command_registry import _COMMAND_SPECS, register_command


def printed_exec(cmd):
    print("about to execute:\n", cmd)
    result = os.system(cmd)
    if result != 0:
        raise RuntimeError(
            "os.system failed for command:\n"
            + cmd
            + "\n\nTry running the command by itself"
        )


def errmsg():
    parser = build_parser()
    parser.print_help()
    sys.exit(1)


_ROOT = os.path.abspath(os.path.dirname(__file__))


def get_data(path):
    "return vbs and js scripts saved as package data"
    return os.path.join(_ROOT, path)


def recursive_include_search(directory, basename, does_it_input):
    with open(
        os.path.join(directory, basename + ".tex"), "r", encoding="utf-8"
    ) as fp:
        alltxt = fp.read()
    # we're only sensitive to the name of the file, not the directory that it's
    # in
    pattern = re.compile(
        r"\n[^%]*\\(?:input|include)[{]((?:[^}]*/)?" + does_it_input + ")[}]"
    )
    for actual_name in pattern.findall(alltxt):
        print(basename + " directly includes " + does_it_input)
        return True, actual_name
    print(
        "file %s didn't directly include '%s' -- I'm going to look for the"
        " files that it includes" % (basename, does_it_input)
    )
    pattern = re.compile(r"\n[^%]*\\(?:input|include)[{]([^}]+)[}](.*)")
    for inputname, extra in pattern.findall(alltxt):
        if "\\input" in extra or "\\include" in extra:
            raise IOError(
                "Don't put multiple include or input statements on one lien"
                " --> are you trying to make my life difficult!!!??? "
            )
        print("%s includes input file:" % basename, inputname)
        retval, actual_name = recursive_include_search(
            directory, os.path.normpath(inputname), does_it_input
        )
        if retval:
            return True, actual_name
    return False, ""


def look_for_pdf(directory, origbasename):
    """look for pdf -- if found return tuple(True, the basename of the pdf, the
    basename of the tex) else return tuple(False, "", "")"""
    found = False
    basename = ""
    actual_name = ""
    for fname in os.listdir(directory):
        if fname[-4:] == ".tex":
            basename = fname[:-4]
            print("found tex file", basename)
            if os.path.exists(os.path.join(directory, basename + ".pdf")):
                print("found matching tex/pdf pair", basename)
                retval, actual_name = recursive_include_search(
                    directory, basename, origbasename
                )
                if retval:
                    return True, basename, actual_name
                if not found:
                    print("but it doesn't seem to include", origbasename)
                    print("about to check for other inputs")
    return found, basename, actual_name


@register_command(
    "Make a python script from a notebook file, following certain rules."
)
def nb2py(arguments):
    assert arguments[0].endswith(".ipynb"), (
        "this is supposed to be called with a .ipynb file argument! (arguments"
        " are %s)" % repr(arguments)
    )
    nb = nbformat.read(arguments[0], nbformat.NO_CONVERT)
    last_was_markdown = False
    jupyter_magic_re = re.compile(r"%(.*)")
    code_counter = 1
    with open(
        arguments[0].replace(".ipynb", ".py"), "w", encoding="utf-8"
    ) as fpout:
        for j in nb.cells:
            lines = j["source"].split("\n")
            if j["cell_type"] == "markdown":
                for line in lines:
                    fpout.write("# " + line + "\n")
                if len(lines[-1]) > 0:
                    # print "markdown, last is",repr(j['source'][-1])
                    fpout.write("\n")
                last_was_markdown = True
            elif j["cell_type"] == "code":
                # fpout.write("start code\n")
                if not last_was_markdown:
                    fpout.write("# In[%d]:\n\n" % code_counter)
                    code_counter += 1
                for line in lines:
                    m = jupyter_magic_re.match(line)
                    if m:
                        fpout.write(
                            "get_ipython().magic(u'%s')\n" % m.groups()[0]
                        )
                    else:
                        fpout.write(line + "\n")
                if len(lines[-1]) > 0:
                    # print "code, last is",repr(j['source'][-1])
                    fpout.write("\n")
                last_was_markdown = False
                # fpout.write("end code\n")
            else:
                raise ValueError("Unknown cell type")


@register_command(
    "Make a notebook file from a python script, following certain rules."
)
def py2nb(arguments):
    jupyter_magic_re = re.compile(
        r"^get_ipython\(\).(?:run_line_)?magic\((?:u?['\"]([^'\"]*)['\"])?"
        + 6 * r"(?:u?, *['\"]([^'\"]*)['\"])?"
        + r"\)"
    )
    jupyter_cellmagic_re = re.compile(
        r"^get_ipython\(\).run_cell_magic\((?:u?['\"]([^'\"]*)['\"])?"
        + 6 * r"(?:u?, *['\"]([^'\"]*)['\"])?"
        + r"\)\)"
    )
    assert len(arguments) == 1, "py2nb should only be called with one argument"
    assert arguments[0].endswith(".py"), (
        "this is supposed to be called with a .py file argument! (arguments"
        " are %s)" % repr(arguments)
    )
    with open(arguments[0], encoding="utf-8") as fpin:
        text = fpin.read()
    text = text.split("\n")
    newtext = []
    in_code_cell = False
    last_line_empty = True
    for thisline in text:
        if thisline.startswith("#"):
            if thisline.startswith("#!") and "python" in thisline:
                pass
            elif thisline.startswith("# coding: utf-8"):
                pass
            elif thisline.startswith("# In["):
                in_code_cell = False
            elif thisline.startswith("# Out["):
                pass
            elif thisline.startswith("# "):
                # this is markdown only if the previous line was empty
                if last_line_empty:
                    newtext.append("# <markdowncell>")
                    in_code_cell = False
                newtext.append(thisline)
            last_line_empty = False
        elif len(thisline) == 0:
            last_line_empty = True
            newtext.append(thisline)
        else:
            if not in_code_cell:
                newtext.append("# <codecell>")
                in_code_cell = True
            m = jupyter_magic_re.match(thisline)
            if m:
                thisline = "%" + " ".join(
                    (j for j in m.groups() if j is not None)
                )
            else:
                m = jupyter_cellmagic_re.match(thisline)
                if m:
                    thisline = "%%" + " ".join(
                        (j for j in m.groups() if j is not None)
                    )
            newtext.append(thisline)
            last_line_empty = False
    text = "\n".join(newtext)

    text += """
# <markdowncell>
# If you can read this, reads_py() is no longer broken! 

    """

    nbook = nbformat.v3.reads_py(text)

    nbook = nbformat.v4.upgrade(nbook)  # Upgrade nbformat.v3 to nbformat.v4
    nbook.metadata.update(
        {
            "kernelspec": {
                "name": "Python [Anaconda2]",
                "display_name": "Python [Anaconda2]",
                "language": "python",
            }
        }
    )

    jsonform = nbformat.v4.writes(nbook) + "\n"
    with open(
        arguments[0].replace(".py", ".ipynb"), "w", encoding="utf-8"
    ) as fpout:
        fpout.write(jsonform)


@register_command(
    "use a compiled latex original (first arg) to generate a synctex file for"
    " a scanned document (second arg), e.g.  with handwritten markup"
)
def gensync(arguments):
    with gzip.open(arguments[0].replace(".pdf", ".synctek.gz")) as fp:
        orig_synctex = fp.read()
        fp.close()
    # since the new synctex is in a new place, I need to tell it
    # how to get back to the original place
    relative_path = os.path.relpath(
        os.path.dir(arguments[0]), os.path.dir(arguments[1])
    )
    base_fname = arguments[0].replace(".pdf", "")
    new_synctex = orig_synctex.replace(base_fname, relative_path + base_fname)
    new_synctex = orig_synctex
    with gzip.open(arguments[1].replace(".pdf", ".synctek.gz")) as fp:
        fp.write(new_synctex)
        fp.write(arguments[1].replace())
        fp.close()


@register_command("rearrange TeX file based on a .rrng plan")
def rrng(arguments):
    rearrange_tex_run(arguments)


@register_command(
    "git forward search, with arguments",
    "git forward search, with arguments\n\n- file\n- line",
)
def gvr(arguments):
    cmd = ["gvim"]
    cmd.append("--remote-wait-silent")
    cmd.append("+" + arguments[1])
    cmd.append(arguments[0])
    subprocess.Popen(" ".join(cmd))  # this is forked
    time.sleep(0.3)
    cmd = ["gvim"]
    cmd.append("--remote-send")
    cmd.append('"zO"')
    time.sleep(0.3)
    cmd = ["gvim"]
    cmd.append("--remote-send")
    cmd.append('":cd %:h\n"')
    subprocess.Popen(" ".join(cmd))


@register_command("match whitespace")
def wmatch(arguments):
    match_spaces.run(arguments)


@register_command("split conflict")
def sc(arguments):
    split_conflict.run(arguments)


@register_command("word diff")
def wd(arguments):
    if arguments[0].find("Temp") > 0:
        # {{{ if it's a temporary file, I need to make a real copy to run
        #     pandoc on
        fp = open(arguments[0], encoding="utf-8")
        contents = fp.read()
        fp.close()
        fp = open(
            arguments[1].replace(".md", "_old.md"), "w", encoding="utf-8"
        )
        fp.write(contents)
        fp.close()
        arguments[0] = arguments[1].replace(".md", "_old.md")
        # }}}
    word_files = [x.replace(".md", ".docx") for x in arguments[:2]]
    local_dir = os.path.dirname(arguments[1])
    print("local directory:", local_dir)
    for j in range(2):
        if arguments[0][-5:] == ".docx":
            print(
                "the first argument has a docx extension, so I'm bypassing the"
                " pandoc step"
            )
        else:
            cmd = ["pandoc"]
            cmd += [arguments[j]]
            cmd += ["--csl=edited-pmid-format.csl"]
            cmd += ["--bibliography library_abbrev_utf8.bib"]
            cmd += ["-s --smart"]
            if len(arguments) > 2:
                if arguments[2][-5:] == ".docx":
                    cmd += ["--reference-docx=" + arguments[2]]
                else:
                    raise RuntimeError(
                        "if you pass three arguments to wd, then the third"
                        " must be a template for the word document"
                    )
            elif os.path.isfile(local_dir + os.path.sep + "template.docx"):
                # by default, use template.docx in the current directory
                cmd += [
                    "--reference-docx="
                    + local_dir
                    + os.path.sep
                    + "template.docx"
                ]
            cmd += ["-o"]
            cmd += [word_files[j]]
            print("about to run", " ".join(cmd))
            os.system(" ".join(cmd))
    cmd = ["start"]
    cmd += [get_data("diff-doc.js")]
    print("word files are", word_files)
    if word_files[0].find("C:") > -1:
        cmd += [word_files[0]]
    else:
        cmd += [os.getcwd() + os.path.sep + word_files[0]]
    cmd += [os.getcwd() + os.path.sep + word_files[1]]
    print("about to run", " ".join(cmd))
    os.system(" ".join(cmd))


@register_command("Reverse search")
def rs(arguments):
    cmd = [
        "gvim",
        "--servername",
        "GVIM",
        "--remote",
        f"+{arguments[0]} {arguments[1]}",
    ]
    os.system(" ".join(cmd))
    cmd = ["wmctrl", "-a", "GVIM"]
    os.system(" ".join(cmd))
    time.sleep(0.5)
    cmd = ["gvim", "--remote-send", "'<esc>zO:cd %:h'<enter>"]
    os.system(" ".join(cmd))


@register_command(
    "smart latex forward-search",
    "smart latex forward-search\n"
    "currently this works specifically for sumatra pdf located\n"
    'at "C:\\Program Files\\SumatraPDF\\SumatraPDF.exe",\n'
    "but can easily be adapted based on os, etc.\n"
    "Add the following line (or something like it) to your vimrc:\n"
    'map <c-F>s :cd %:h\\|sil !pydifft fs %:p <c-r>=line(".")<cr><cr>\n'
    "it will map Cntrl-F s to a forward search.",
)
def fs(arguments):
    texfile, lineno = arguments
    texfile = os.path.normpath(os.path.abspath(texfile))
    directory, texfile = texfile.rsplit(os.path.sep, 1)
    assert texfile[-4:] == ".tex", "needs to be called .tex"
    origbasename = texfile[:-4]
    if os.name == "posix":
        # linux
        cmd = ["zathura --synctex-forward"]
        assert shutil.which("zathura"), (
            "first, install zathura, then set ~/.config/zathura/zathurarc"
            "to include"
            'set synctex-editor-command "pydifft rs %{line} %{input}"'
        )
    else:
        # windows
        cmd = ["start sumatrapdf -reuse-instance"]
    if os.path.exists(os.path.join(directory, origbasename + ".pdf")):
        temp = os.path.join(directory, origbasename + ".pdf")
        cmd.append(f"{lineno}:0:{texfile} {temp}")
        tex_name = origbasename
    else:
        print("no pdf file for this guy, looking for one that has one")
        found, basename, tex_name = look_for_pdf(directory, origbasename)
        if not found:
            while os.path.sep in directory and directory.lower()[-1] != ":":
                build_nb = os.path.join(directory, "build_nb")
                directory, _ = directory.rsplit(os.path.sep, 1)
                if os.path.exists(build_nb):
                    print("looking for a build_nb subdirectory")
                    found, basename, tex_name = look_for_pdf(
                        build_nb, origbasename
                    )
                    if found:
                        directory = build_nb
                        break
                print("looking one directory up, in ", directory)
                found, basename, tex_name = look_for_pdf(
                    directory, origbasename
                )
                if found:
                    break
        if not found:
            raise IOError("This is not the PDF you are looking for!!!")
        print("result:", directory, origbasename, found, basename, tex_name)
        # file has been found, so add to the command
        cmd.append(
            f"{lineno}:0:{tex_name}.tex"
            f" {os.path.join(directory, basename + '.pdf')}"
        )
    if os.name == "posix":
        cmd.append("&")
    else:
        cmd.append("-forward-search")
        cmd.append(tex_name + ".tex")
        cmd.append("%s -fwdsearch-color ff0000" % lineno)
    print("changing to directory", directory)
    os.chdir(directory)
    print("about to execute:\n\t", " ".join(cmd))
    os.system(" ".join(cmd))
    if os.name == "posix":
        cmd = ["wmctrl", "-a", basename + ".pdf"]
        os.system(" ".join(cmd))


@register_command("Convert xml to xlsx")
def xx(arguments):
    format_codes = {
        "csv": 6,
        "xlsx": 51,
        "xml": 46,
    }  # determined by microsoft vbs
    cmd = ["start"]
    cmd += [get_data("xml2xlsx.vbs")]
    first_ext = arguments[0].split(".")[-1]
    second_ext = arguments[1].split(".")[-1]
    for j in arguments[0:2]:
        if j.find("C:") > -1:
            cmd += [j]
        else:
            cmd += [os.getcwd() + os.path.sep + j]
    cmd += [str(format_codes[j]) for j in [first_ext, second_ext]]
    print("about to run", " ".join(cmd))
    os.system(" ".join(cmd))


@register_command("compare files, and rank by how well they compare")
def cmp(arguments):
    target = arguments[0]
    arguments = arguments[1:]
    with open(target, encoding="utf-8") as fp:
        base_txt = fp.read()
    retval = {}
    for j in arguments:
        with open(j, encoding="utf-8") as fp:
            retval[j] = difflib.SequenceMatcher(
                None, base_txt, fp.read()
            ).ratio()
    print(
        "\n".join(
            str(v) + "-->" + str(k)
            for k, v in sorted(
                retval.items(), key=lambda item: item[1], reverse=True
            )
        )
    )


@register_command("tex separate comments")
def sepc(arguments):
    tex_sepcomments(arguments[0])


@register_command("tex unseparate comments")
def unsepc(arguments):
    tex_unsepcomments(arguments[0])


@register_command("convert annotated TeX sources to DOCX via pandoc")
def tex2docx(arguments):
    filename = arguments[0]
    assert filename[-4:] == ".tex"
    basename = filename[:-4]
    with open("%s.tex" % basename, "r", encoding="utf-8") as fp:
        content = fp.read()
    comment_re = re.compile(r"\\pdfcomment([A-Z]+)\b")
    thismatch = comment_re.search(
        content
    )  # match doesn't work with newlines, apparently
    while thismatch:
        a = thismatch.start()
        b, c = matchingbrackets(content, a, "{")
        content = (
            content[:a]
            + content[a + 1 : b]
            + "("
            + content[b + 1 : c]
            + ")"
            + content[c + 1 :]
        )
        thismatch = comment_re.search(content)
    with open("%s_parencomments.tex" % basename, "w", encoding="utf-8") as fp:
        fp.write(r"\renewcommand{\nts}[1]{\textbf{\textit{#1}}}" + "\n")
        fp.write(content)
    printed_exec(
        "pandoc %s_parencomments.tex -f latex+latex_macros -o %s.md"
        % ((basename,) * 2)
    )
    with open("%s.md" % basename, "r", encoding="utf-8") as fp:
        content = fp.read()
    thisid = 2
    comment_re = re.compile(r"pdfcomment([A-Z]+)\(")
    thismatch = comment_re.search(
        content
    )  # match doesn't work with newlines, apparently
    while thismatch:
        a = thismatch.start()
        b, c = matchingbrackets(content, a, "(")
        author = thismatch.groups()[0]
        content = (
            content[:a]
            + '[%s]{.comment-start id="%d" author="%s"}'
            % (content[b + 1 : c], thisid, author)
            + '[]{.comment-end id="%d"}' % thisid
            + content[c + 1 :]
        )
        thisid += 1
        thismatch = comment_re.search(content)
    with open("%s.md" % basename, "w", encoding="utf-8") as fp:
        fp.write(content)
    printed_exec("pandoc %s.md -o %s.docx" % ((basename,) * 2))
    printed_exec("start %s.docx" % (basename))


@register_command("convert DOCX documents back to TeX while cleaning markup")
def docx2tex(arguments):
    filename = arguments[0]
    assert filename[-5:] == ".docx"
    basename = filename[:-5]
    printed_exec(
        "pandoc %s.docx --track-changes=all -o %s.md" % ((basename,) * 2)
    )
    with open("%s.md" % basename, "r", encoding="utf-8") as fp:
        content = fp.read()
    citation_re = re.compile(r"\\\[\\@")
    thismatch = citation_re.search(
        content
    )  # match doesn't work with newlines, apparently
    while thismatch:
        a, b = matchingbrackets(content, thismatch.start(), "[")
        content = (
            content[: a - 1] + content[a:b].replace("\\", "") + content[b:]
        )
        thismatch = citation_re.search(content)
    with open("%s.md" % basename, "w", encoding="utf-8") as fp:
        fp.write(content)
    printed_exec(
        "pandoc %s.md --biblatex -r markdown-auto_identifiers -o %s_reconv.tex"
        % ((basename,) * 2)
    )
    print("about to match spaces:")
    match_spaces.run((basename + ".tex", basename + "_reconv.tex"))
    with open("%s_reconv.tex" % basename, "r", encoding="utf-8") as fp:
        content = fp.read()
    citation_re = re.compile(r"\\autocite\b")
    content = citation_re.sub(r"\\cite", content)
    paragraph_re = re.compile(r"\n\n(\\paragraph{.*)\n\n")
    content = paragraph_re.sub(r"\1", content)
    # {{{ convert \( to dollars
    math_re = re.compile(r"\\\(")
    thismatch = math_re.search(
        content
    )  # match doesn't work with newlines, apparently
    while thismatch:
        a = thismatch.start()
        b, c = matchingbrackets(content, a, "(")
        content = (
            content[:a] + "$" + content[a + 1 : b] + "$" + content[c + 1 :]
        )
        thismatch = math_re.search(content)
    # }}}
    with open("%s_reconv.tex" % basename, "w", encoding="utf-8") as fp:
        fp.write(content)


@register_command(
    "make a gzip file suitable for arxiv (currently only test on linux)"
)
def arxiv(arguments):
    ROOT_TEX = arguments[0].strip(".tex")
    project_name = Path.cwd().name
    TARGET_DIR = Path(f"../{project_name}_forarxiv/")
    include_suppinfo = False
    copy_image_files(ROOT_TEX, project_name, TARGET_DIR, include_suppinfo)
    os.chdir(Path.cwd().parent)
    output_filename = f"{project_name}_forarxiv.tgz"
    # create tar process
    tar = subprocess.Popen(
        ["tar", "cf", "-", TARGET_DIR.name], stdout=subprocess.PIPE
    )
    # create gzip process, using tar's stdout as its stdin
    gzip = subprocess.Popen(
        ["gzip", "-9"], stdin=tar.stdout, stdout=subprocess.PIPE
    )
    # close tar's stdout so it doesn't hang around waiting for input
    tar.stdout.close()
    # write gzip's stdout to a file
    with open(output_filename, "wb") as fp:
        shutil.copyfileobj(gzip.stdout, fp)
    gzip.stdout.close()


@register_command(
    "look for the file myacronyms.sty (locally or in texmf) and use it"
    " substitute your acronyms"
)
def ac(arguments):
    # Run kpsewhich and capture the output
    kpsewhich_output = subprocess.run(
        ["kpsewhich", "myacronyms.sty"], capture_output=True, text=True
    )

    # Convert the string to a pathlib Path object if the file was found, else
    # assign None
    path = (
        Path(kpsewhich_output.stdout.strip())
        if kpsewhich_output.returncode == 0
        else None
    )
    print("I'm using the acronyms in", path)
    replace_acros(path)


@register_command(
    "Paste mark down as formatted text into email, etc. (Tested on linux)"
)
def pmd(arguments):
    # pandoc input.md -t html -o - | xclip -selection clipboard -t text/html
    p1 = subprocess.Popen(
        ["pandoc", arguments[0], "-t", "html", "-o", "-"],
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        ["xclip", "-selection", "clipboard", "-t", "text/html"],
        stdin=p1.stdout,
        check=True,
    )
    p1.stdout.close()
    p1.wait()


@register_command(
    "Save tex file as outline, with filename_outline.pickle storing content"
    " and filename_outline.md giving outline."
)
def xo(arguments):
    assert len(arguments) == 1
    outline.extract_outline(arguments[0])


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True
    for name, spec in _COMMAND_SPECS.items():
        subparser = subparsers.add_parser(
            name,
            help=spec["help"],
            description=spec["description"],
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        arguments = []
        if "arguments" in spec:
            arguments = spec["arguments"]
        for argument in arguments:
            flags = argument["flags"]
            kwargs = dict(argument["kwargs"])
            subparser.add_argument(*flags, **kwargs)
        subparser.set_defaults(_handler=spec["handler"])
    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    if not argv:
        parser.print_help()
        return
    namespace = parser.parse_args(argv)
    handler = namespace._handler
    handler_kwargs = dict(vars(namespace))
    handler_kwargs.pop("_handler", None)
    handler_kwargs.pop("command", None)
    handler(**handler_kwargs)


if __name__ == "__main__":
    main()
