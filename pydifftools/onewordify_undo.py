# again rerun
from lxml import html, etree
import os
from matlablike import *
from unidecode import unidecode
import re
import sys

fp = open(sys.argv[1], "r")
needsspace_re = re.compile(r'(\w[):;"\-\.,!?}]*) +(["(]*\w)')
paragraphcommands_re = re.compile(r"^ *\\(sub)*paragraph{.*}")
commentline_re = re.compile(r"^ *%")
normalline_re = re.compile(r"^\(%SPACE%\)\|\(%NEWLINE%\)")
notweird_re = re.compile(r"^(%SPACE%)|(%\[ORIG%)|(%ORIG\]\[NEW%)|(%NEW\]%)")
text_list = []
found_beginning = False
print("opened", sys.argv[1])
# {{{ pull out just the part between the document text
for thisline in fp:
    if (
        (thisline[:7] == "<<<<<<<")
        or (thisline[:7] == "=======")
        or (thisline[:7] == ">>>>>>>")
    ):
        text_list.append(
            "%NEWLINE% %CONFLICT%" + thisline.strip() + "%NEWLINE%"
        )
    else:
        text_list.append(thisline.rstrip())
fp.close()
text_list = [x.replace("%NEWLINE%", "\n") for x in text_list]
# {{{ don't mess with the "special" lines
for j, thisline in enumerate(text_list):
    if not notweird_re.match(thisline):
        if paragraphcommands_re.match(thisline) or commentline_re.match(
            thisline
        ):
            print("found special line '", thisline, "'")
            text_list[j] = thisline.replace(" ", " %SPACE% ")
# }}}
text_list = " ".join(text_list)
text_list = needsspace_re.sub(r"\1 %SPACE% \2", text_list)
text_list = needsspace_re.sub(
    r"\1 %SPACE% \2", text_list
)  # again to catch the single letter ones
text_list = text_list.replace(" ", "")
text_list = text_list.replace("%SPACE%", " ")
# {{{ write out the result
newfile = re.sub(r"(.*)(\..*)", r"\1_1wordcollapse\2", sys.argv[1])
fp = open(newfile, "w")
outputtext = "".join(text_list)
fp.write(outputtext)
fp.close()
# }}}
