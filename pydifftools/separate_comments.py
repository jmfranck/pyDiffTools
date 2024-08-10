import re
import sys
import codecs

sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
from .comment_functions import (
    generate_alphabetnumber,
    matchingbrackets,
    comment_definition,
)


def tex_sepcomments(texfile):
    if texfile[-4:] == ".tex":
        base_filename = texfile[:-4]
        print("yes, a tex file called", base_filename, ".tex")
    else:
        raise RuntimeError("not a tex file??")
    with open(base_filename + ".tex", "r", encoding="utf-8") as fp:
        content = fp.read()
    comment_string = "%%NUMBER OF COMMENTS"
    a = content.find(comment_string)
    if a > 0:
        b = content.find("\n", a + len(comment_string))
        num_matches = int(content[a + len(comment_string) : b])
        print("found %d comments already!" % num_matches)
    else:
        num_matches = 0
    content = content.replace(
        r"\begin{document}",
        "\\include{%s_comments}\n\\begin{document}" % base_filename,
    )
    comment_collection = ""
    names = ["pdfcommentAG", "pdfcommentAB", "pdfcommentJF", "pdfcommentG"]
    name_list = "(" + "|".join(names) + ")"
    comment_re = re.compile(r"\\%s([\[\{])" % (name_list))
    thismatch = comment_re.search(
        content
    )  # match doesn't work with newlines, apparently
    while thismatch:
        before = content[: thismatch.start()]
        thisname, bracket_type = thismatch.groups()
        a, b = matchingbrackets(content, thismatch.start(), bracket_type)
        if bracket_type == "[":
            highlight = content[a + 1 : b]
            a, b = matchingbrackets(content, b, "{")
            print("found comment:", content[a : b + 1])
            comment = content[a + 1 : b]
            endpoint = b
        else:
            highlight = ""
            comment = content[a + 1 : b]
            endpoint = b
        after = content[endpoint + 1 :]
        # replace and search again
        print("type of num_matches", num_matches, type(num_matches))
        envstring = thisname + generate_alphabetnumber(num_matches)
        print("%s--------------------" % envstring)
        print("highlight:\n", highlight)
        print("comment:\n", comment)
        print("--------------------")
        print("before replace:\n", content[thismatch.start() : endpoint])
        content = before + r"\%s" % envstring + "{" + highlight + "}" + after
        print("--------------------")
        print("after replace:\n", content[thismatch.start() : endpoint])
        print("--------------------")
        comment_collection += comment_definition(envstring, thisname, comment)
        thismatch = comment_re.search(content)
        num_matches += 1
    with open(base_filename + ".tex", "w", encoding="utf-8") as fp:
        comment_string = "%%%%NUMBER OF COMMENTS %d\n" % num_matches
        content = content.replace(
            r"\begin{document}", comment_string + "\\begin{document}"
        )
        fp.write(content)
    with open(base_filename + "_comments.tex", "w", encoding="utf-8") as fp:
        fp.write(comment_collection)
