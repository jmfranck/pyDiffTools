# again rerun
from lxml import html, etree
import os
from matlablike import *
from unidecode import unidecode
import re
import sys

fp = open(sys.argv[1], "r")
paragraphcommands_re = re.compile(r"^ *\\(sub)*paragraph{.*}")
commentline_re = re.compile(r"^ *%")
beginlatex_re = re.compile(r"^[^#]*\\begin{document}(.*)")
endlatex_re = re.compile(r"^([^#]*)\\end{document}.*")
commandstart_re = re.compile(r"(\\[a-zA-Z]+[\[{])")
word_citation_re = re.compile(r"(\[[0-9 ,]+\][,\.)]*)")
tex_citation_re = re.compile(r"(.*)(\\cite{[a-zA-Z0-9,_]+}[,\.)]*)(.*)$")
tex_ref_re = re.compile(r"(.*)(\\c*ref{[a-zA-Z0-9,_:\-]+}[,\.)]*)(.*)$")
text_list = []
if sys.argv[1][-4:] == ".tex":
    latex_file = True
else:
    latex_file = False
found_beginning = False
start_line = 0
end_line = 0
print("opened", sys.argv[1])
# {{{ pull out just the part between the document text
j = 0
for thisline in fp:
    thisline = thisline.replace("\xa0", " ")  # because word sucks
    thisline = thisline.replace(
        "\x93", "``"
    )  # this and following are just pulled from vim
    thisline = thisline.replace("\x94", "''")
    thisline = thisline.replace("\x96", "--")
    j += 1
    if latex_file:
        if not found_beginning:
            thismatch = beginlatex_re.match(thisline)
            if thismatch:
                text_list.append(thismatch.groups()[0].rstrip())
                found_beginning = True
                start_line = j + 1
                print("Found the beginning at line", start_line)
        else:
            thismatch = endlatex_re.match(thisline)
            if thismatch:
                text_list.append(thismatch.groups()[0].rstrip())
                print("Found the end")
                end_line = j
                print("Found the end at line", end_line)
        text_list.append(thisline)
    else:
        text_list.append(
            thisline.replace("$$", "")
        )  # no better place to check for the tex dollar sign double-up
if end_line == 0:
    end_line = len(text_list)
fp.close()
j = 0
while j < len(
    text_list
):  # first, put citations on their own line, so I can next treat them as special lines
    thismatch = tex_citation_re.match(text_list[j])
    othermatch = tex_ref_re.match(text_list[j])
    if othermatch:
        thismatch = othermatch
    if thismatch:
        text_list.pop(j)
        text_list.insert(
            j, thismatch.groups()[2]
        )  # push on backwards, so it shows up in the right order
        text_list.insert(
            j,
            thismatch.groups()[1].replace(" ", "\n%SPACE%\n")
            + "%NONEWLINE%\n",
        )  # since these are "fake" newlines, make sure they don't get broken! -- also to preserve spaces, I'm pre-processing the spacing here
        text_list.insert(
            j,
            thismatch.groups()[0].replace(" ", "\n%SPACE%\n")
            + "%NONEWLINE%\n",
        )
        print(
            "found citation or reference, broke line:",
            text_list[j],
            text_list[j + 1],
            text_list[j + 2],
        )
        print("---")
        j += 1  # so that we skip the citation we just added
        end_line += 2  # because we added two lines
    j += 1
for j in range(0, len(text_list)):
    thismatch = paragraphcommands_re.match(text_list[j])
    if thismatch:
        text_list[j] = text_list[j].replace(
            "\n", "%NEWLINE%\n"
        )  # these lines are protected/preserved from being chopped up, since they are invisible
        print("found paragraph line:", text_list[j])
    else:
        thismatch = tex_citation_re.match(text_list[j])
        if not thismatch:
            thismatch = tex_ref_re.match(text_list[j])
        if thismatch:
            print("found citation line:", text_list[j])
        else:
            text_list[j] = text_list[j].replace("~", "\n~\n")
            text_list[j] = commandstart_re.sub("\\1\n", text_list[j])
            text_list[j] = word_citation_re.sub("\n\\1\n", text_list[j])
            text_list[j] = text_list[j].replace("}", "\n}\n")
            text_list[j] = text_list[j].replace("]{", "\n]{\n")
            text_list[j] = text_list[j].replace(" ", "\n%SPACE%\n")
        if text_list[j][-12:] == "%NONEWLINE%\n":
            print("trying to drop NONEWLINE going from:")
            print(text_list[j])
            text_list[j] = text_list[j][:-12] + "\n"
            print("to:\n", text_list[j])
        else:
            print("line ends in:", text_list[j][-12:])
            text_list[j] += "%NEWLINE%\n"
            text_list[j] = text_list[j].replace("\r", "\n%NEWLINE%\n")
# }}}
# {{{ write out the result
outputtext = "".join(text_list)
outputtext = outputtext.split("\n")
outputtext = [j for j in outputtext if len(j) > 0]
if not latex_file:  # easier to just strip the tags here
    print("this is not a latex file")
    outputtext = [j for j in outputtext if j != "%SPACE%" and j != "%NEWLINE%"]
else:
    print("this is a latex file")
    outputtex = "".join(
        text_list[start_line:end_line]
    )  # up to but not including the end document
    outputtex = outputtex.split("\n")
    outputtex = [j for j in outputtex if len(j) > 0]
    outputtex = [
        j for j in outputtex if j[0] != "%"
    ]  # takes care of space and newline as well as tex comments
newfile = re.sub(r"(.*)(\..*)", r"\1_1word\2", sys.argv[1])
fp = open(newfile, "w")
fp.write("\n".join(outputtext))
fp.close()
if latex_file:
    newfile = re.sub(r"(.*)(\..*)", r"\1_1wordstripped\2", sys.argv[1])
    fp = open(newfile, "w")
    fp.write("\n".join(outputtex))
    fp.close()
# }}}
