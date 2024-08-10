import re
import sys
import codecs

sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
from .comment_functions import generate_alphabetnumber, matchingbrackets


def tex_unsepcomments(texfile):
    if texfile[-12:] == "_sepcomm.tex":
        base_filename = texfile[:-12]
        print("yes, a _sepcomm.tex file called", base_filename, ".tex")
    elif texfile[-4:] == ".tex":
        base_filename = texfile[:-4]
        print("yes, a .tex file called", base_filename, ".tex")
    else:
        raise RuntimeError("not a tex file??")
    with open(base_filename + "_comments.tex", "r", encoding="utf-8") as fp:
        content = fp.read()
    # comment_def_re = re.compile(r"\\newcommand\{\%s[A-Z]+")
    names = ["pdfcommentAG", "pdfcommentAB", "pdfcommentJF", "pdfcommentG"]
    list_of_names = []
    list_of_commands = []
    list_of_content = []
    for j in range(0, len(names)):
        comment_def_re = re.compile(
            r"\\newcommand\{\\(%s[a-z]+)\}\{" % (names[j])
        )
        for m in comment_def_re.finditer(content):
            print("found %d:%d" % (m.start(), m.end()), m.groups()[0])
            print("text:", content[m.start() : m.end()])
            a, b = matchingbrackets(content, m.end() - 1, "{")
            print("found from %d to %d" % (a, b))
            print("-----content------")
            print(content[a : b + 1])
            print("------------------")
            list_of_names.append(names[j])
            list_of_commands.append(m.groups()[0])
            list_of_content.append(content[a + 1 : b])
    with open(texfile, "r", encoding="utf-8") as fp:
        content = fp.read()
    for j in range(0, len(list_of_names)):
        a = content.find("\\%s" % list_of_commands[j])
        if a < 0:
            raise RuntimeError(
                "couldn't find command \\%s" % list_of_commands[j]
            )
        else:
            starthighlight, b = matchingbrackets(content, a, "{")
            highlight = content[starthighlight + 1 : b]
            print(
                "found command \\%s with highlight {%s} and going to add content {%s}"
                % (list_of_commands[j], highlight, list_of_content[j])
            )
            if len(highlight) > 0:
                content = (
                    content[:a]
                    + "\\%s[%s]{%s}"
                    % (list_of_names[j], highlight, list_of_content[j])
                    + content[b + 1 :]
                )
            else:
                content = (
                    content[:a]
                    + "\\%s{%s}" % (list_of_names[j], list_of_content[j])
                    + content[b + 1 :]
                )
    content = re.sub("\\\\include{%s_comments}\n" % base_filename, "", content)
    content = re.sub("%%NUMBER OF COMMENTS [0-9]+ *\n", "", content)
    with open(base_filename + ".tex", "w", encoding="utf-8") as fp:
        fp.write(content)
        print("wrote output to", base_filename + ".tex")
