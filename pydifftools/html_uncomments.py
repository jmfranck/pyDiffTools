# again rerun
from lxml import html, etree
import os
from pyspecdata import *
from unidecode import unidecode
import re
import sys
from .comment_functions import (
    generate_alphabetnumber,
    matchingbrackets,
    comment_definition,
)

manual_math_conversion = (
    False  # this hacks some stuff that pandoc does much better
)
fp = open(sys.argv[1], "r")
content = fp.read()
fp.close()
# comrefwithnewline_re = re.compile(r"('mso-comment-reference:[^']*)[\n ]+")
# {{{ need to remove weird linebreaks with the following, or it doesn't interpret the styles correctly
newcontent = re.sub(r":\n *", r":", content)
content = newcontent
newcontent = re.sub(r"('mso-comment-reference:[^']*)[\n ]+", r"\1", content)
while content != newcontent:
    content = newcontent
    newcontent = re.sub(
        r"('mso-comment-reference:[^']*)[\n ]+", r"\1", content
    )
content = newcontent
newcontent = re.sub(
    r"('mso-comment-reference:[^'\"]*[^;])(['\"])", r"\1;\2", content
)
while content != newcontent:
    content = newcontent
    newcontent = re.sub(
        r"('mso-comment-reference:[^'\"]*[^;])(['\"])", r"\1;\2", content
    )
content = newcontent
content = content.replace(r"\%", r"%EXPLICITPAREN%")
content = content.replace(r"%", r"%EXPLICITPAREN%")
content = content.replace(r"%EXPLICITPAREN%", r"\%")
if manual_math_conversion:
    content = content.replace(
        "&#916;", r"%ENTERMATHMODE%\Delta%LEAVEMATHMODE%"
    )
    content = content.replace("\xb0C", r"\degC ")
    content = content.replace(" \xb5M", r"\uM ")
    content = content.replace("\xb5M", r"\uM ")
    content = content.replace(
        "&#945;", r"%ENTERMATHMODE%\alpha%LEAVEMATHMODE%"
    )
    content = content.replace("&#946;", r"%ENTERMATHMODE%\beta%LEAVEMATHMODE%")
    content = content.replace(
        "&#947;", r"%ENTERMATHMODE%\gamma%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#948;", r"%ENTERMATHMODE%\delta%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#949;", r"%ENTERMATHMODE%\varepsilon%LEAVEMATHMODE%"
    )
    content = content.replace("&#950;", r"%ENTERMATHMODE%\zeta%LEAVEMATHMODE%")
    content = content.replace("&#951;", r"%ENTERMATHMODE%\eta%LEAVEMATHMODE%")
    content = content.replace(
        "&#952;", r"%ENTERMATHMODE%\theta%LEAVEMATHMODE%"
    )
    content = content.replace("&#953;", r"%ENTERMATHMODE%\iota%LEAVEMATHMODE%")
    content = content.replace(
        "&#954;", r"%ENTERMATHMODE%\kappa%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#955;", r"%ENTERMATHMODE%\lambda%LEAVEMATHMODE%"
    )
    content = content.replace("&#956;", r"%ENTERMATHMODE%\mu%LEAVEMATHMODE%")
    content = content.replace("&#957;", r"%ENTERMATHMODE%\nu%LEAVEMATHMODE%")
    content = content.replace("&#958;", r"%ENTERMATHMODE%\xi%LEAVEMATHMODE%")
    content = content.replace(
        "&#959;", r"%ENTERMATHMODE%\omicron%LEAVEMATHMODE%"
    )
    content = content.replace("&#960;", r"%ENTERMATHMODE%\pi%LEAVEMATHMODE%")
    content = content.replace("&#961;", r"%ENTERMATHMODE%\rho%LEAVEMATHMODE%")
    content = content.replace(
        "&#963;", r"%ENTERMATHMODE%\sigma%LEAVEMATHMODE%"
    )
    content = content.replace("&#964;", r"%ENTERMATHMODE%\tau%LEAVEMATHMODE%")
    content = content.replace(
        "&#966;", r"%ENTERMATHMODE%\varphi%LEAVEMATHMODE%"
    )
    content = content.replace("&#967;", r"%ENTERMATHMODE%\chi%LEAVEMATHMODE%")
    content = content.replace("&#968;", r"%ENTERMATHMODE%\psi%LEAVEMATHMODE%")
    content = content.replace(
        "&#969;", r"%ENTERMATHMODE%\omega%LEAVEMATHMODE%"
    )
    content = content.replace("&#8242;", r"%ENTERMATHMODE%\'%LEAVEMATHMODE%")
    content = content.replace("&#8212;", r"--")
    content = content.replace("&#8217;", r"'")
    content = content.replace("&#8220;", r"``")
    content = content.replace("&#8221;", r"''")
    content = content.replace("&#8476;", r"%ENTERMATHMODE%\Re%LEAVEMATHMODE%")
    content = content.replace(
        "&#8658;", r"%ENTERMATHMODE%\Rightarrow%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#8656;", r"%ENTERMATHMODE%\Leftarrow%LEAVEMATHMODE%"
    )
    content = content.replace("&#8721;", r"%ENTERMATHMODE%\Sum%LEAVEMATHMODE%")
    content = content.replace("&#8722;", r"--")
    content = content.replace("&#8725;", r"/")
    content = content.replace("&#8727;", r"%ENTERMATHMODE%^*%LEAVEMATHMODE%")
    content = content.replace("&#8764;", r"%ENTERMATHMODE%\sim%LEAVEMATHMODE%")
    content = content.replace(
        "&#8733;", r"%ENTERMATHMODE%\propto%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#8734;", r"%ENTERMATHMODE%\infty%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#8776;", r"%ENTERMATHMODE%\approx%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#8801;", r"%ENTERMATHMODE%\equiv%LEAVEMATHMODE%"
    )
    content = content.replace("&#8804;", r"%ENTERMATHMODE%\le%LEAVEMATHMODE%")
    content = content.replace("&#8805;", r"%ENTERMATHMODE%\ge%LEAVEMATHMODE%")
    content = content.replace("&#8810;", r"%ENTERMATHMODE%\ll%LEAVEMATHMODE%")
    content = content.replace("&#8811;", r"%ENTERMATHMODE%\gg%LEAVEMATHMODE%")
    content = content.replace(
        "&#8901;", r"%ENTERMATHMODE%\cdot%LEAVEMATHMODE%"
    )
    content = content.replace(
        "&#120098;", r"%ENTERMATHMODE%\mathfrak{e}%LEAVEMATHMODE%"
    )
    content = content.replace(
        "$$", ""
    )  # math symbols doubled back on each other
# }}}
# content = re.sub(r'mso-comment-reference:([a-zA-Z_0-9]+)&amp;([a-zA-Z_0-9]+)',r'mso-comment-reference:\1AMPERSAND\2',content)
# content = re.sub(r'mso-comment-reference:[\n ]*([a-zA-Z0-9]+)',r'narg!mso-comment-reference:\1',content)
doc = html.fromstring(content)
commentlabel_re = re.compile(r"\[([A-Z]+)([0-9])\]")
inlineequation_re = re.compile(r"\$([^\$]*)\$")
# for j in doc.xpath('descendant::*[@style="mso-element:comment"]'):
thisbody = doc.find("body")
print("I found the body", lsafen(thisbody))
# commentlist = etree.Element('div',style = 'mso-element:comment-list')
num = 0
numcomments = 0
numcompara = 0
comment_dict = {}
comment_label_re = re.compile(r"_com_([0-9]+)")
for j in doc.xpath('//*[contains(@style,"font-family:Symbol")]'):
    print('found symbol with text"', j.text, '" and dropped the tag')
    j.drop_tag()
for j in doc.xpath('//div[@style="mso-element:comment-list"]'):
    num += 1
    for k in j.xpath('descendant-or-self::*[@style="mso-element:comment"]'):
        numcomments += 1
        numcompara = 0
        commenttext = []

        def process_comment_text(thistag, numcompara, commenttext):
            for m in k.find_class("msocomtxt"):
                mymatch = comment_label_re.match(m.attrib["id"])
                if mymatch:
                    commentlabel = mymatch.groups()[0]
                    print("that means it's comment", commentlabel)
                else:
                    raise ValueError(
                        "I don't understand what the comment id "
                        + m.attrib["id"]
                        + " means"
                    )
            numcompara += 1
            for m in thistag.xpath(
                'descendant-or-self::span[@style="mso-special-character:comment"]'
            ):
                m.drop_tree()
                print("dropped special character")
            commenttext.append(unidecode(thistag.text_content()))
            return commentlabel, numcompara

        found_something = False
        class_types = ["MsoCommentText", "MsoNormal", "indent", "noindent"]
        for class_type in class_types:
            for l in k.find_class(class_type):
                commentlabel, numcompara = process_comment_text(
                    l, numcompara, commenttext
                )
                found_something = True
        if not found_something:
            print(
                (
                    "Wargning: I found no "
                    + ",".join(class_types)
                    + " in this comment --\n%s\n -- in the future, should search by paragraph tag, instead"
                    % html.tostring(k)
                )
            )
        k.drop_tree()  # drop the stuff at the end
        print(
            "for comment %d, I find %d paragraphs" % (numcomments, numcompara)
        )
        comment_dict[commentlabel] = "\n\n".join(commenttext)
        print("text looks like this:", comment_dict[commentlabel])
        # and load into the dictionary
        # {{{ remove the children, set the comment text as the text, and drop the tag
        # for l in k.getchildren():
        #    l.drop_tree()
        # k.text = '\n\n'.join(commenttext)
        # k.drop_tag()
        # }}}
        # print 'comment %d is:'%numcomments,html.tostring(k)
        #    print 'for comment',numcomments,':'
        #    print unicode(l.text_content()).encode('utf-8')
    # print 'found span with style:\n\n',lsafen(html.tostring(j),wrap = 60)
    # if j.attrib['style'] == 'mso-element:comment':
    # print 'found div with style:\n\n',lsafen(j.attrib,wrap = 60)
    #    print "found p with class MsoCommentText:"
    #    print unicode(k.text_content()).encode('utf-8')
    # j.drop_tree()
    # j.append("a comment found here")
    # commentlist.append(j)
print("I found %d comment lists and %d comments" % (num, numcomments))
initial_translation_dict = {
    "JF": "john",
    "y": "yuan",
    "CoLA&S": "peter",
    "SH": "songi",
    "PQ": "peter",
    "KE": "keith",
}
commentlabel_re = re.compile(r"\[([A-Za-z&]+)([0-9]+)\]")
commentid_re = re.compile(r"_anchor_([0-9]+)")
numcomrefs = 0
numcomrefsrepd = 0
comment_file_text = ""
current_comment_number = 0
for thiscommentreference in doc.find_class("MsoCommentReference"):
    thiscommentreference.drop_tag()
for thiscommentreference in doc.find_class("msocomanchor"):
    comref_text = thiscommentreference.text
    if comref_text is not None:
        m = commentlabel_re.match(comref_text)
        if m:
            initials, number = m.groups()
            try:
                print(
                    "I found comment %s by %s"
                    % (number, initial_translation_dict[initials])
                )
            except KeyError:
                raise ValueError(
                    "I don't know who %s is -- add to initial_translation_dict"
                    % initials
                )
            thiscommentreference.text = ""
            thiscommentreference.drop_tag()
            prevcomrefsrepd = numcomrefsrepd
            for k in doc.xpath(
                'descendant-or-self::*[contains(@style,"mso-comment-reference:%s_%s;")]'
                % (initials, number)
            ):
                print("\nThis reference has the text:", html.tostring(k))
                if k.text is None:
                    k.text = ""
                empty_tag = False
                if k.text == "":
                    empty_tag = True
                if number not in list(comment_dict.keys()):
                    raise KeyError(
                        repr(number)
                        + "is not in comment_dict keys: "
                        + repr(list(comment_dict.keys()))
                    )
                if (
                    (len(comment_dict[number]) > 13)
                    and (comment_dict[number][:14] == "(need to do:) ")
                    and (initial_translation_dict[initials] == "john")
                ):  # if it's a "need to do"
                    # k.text = r'\%s['%('ntd')+k.text_content().replace('[',' ').replace(']',' ')+']{'+comment_dict[number][14:]+'}'
                    k.text = (
                        r"\%s%s{"
                        % (
                            "ntd",
                            generate_alphabetnumber(current_comment_number),
                        )
                        + k.text_content().replace("[", " ").replace("]", " ")
                        + "}"
                    )
                    comment_file_text += comment_definition(
                        "ntd"
                        + generate_alphabetnumber(current_comment_number),
                        "ntd",
                        comment_dict[number][14:],
                    )
                    current_comment_number += 1
                else:
                    k.text = (
                        r"\%s%s{"
                        % (
                            initial_translation_dict[initials],
                            generate_alphabetnumber(current_comment_number),
                        )
                        + k.text_content().replace("[", " ").replace("]", " ")
                        + "}"
                    )
                    comment_file_text += comment_definition(
                        initial_translation_dict[initials]
                        + generate_alphabetnumber(current_comment_number),
                        initial_translation_dict[initials],
                        comment_dict[number],
                    )
                    current_comment_number += 1
                k.drop_tag()
                print("I convert it to this:", html.tostring(k))
                numcomrefsrepd += 1
            # if numcomrefsrepd > prevcomrefsrepd+1:
            #    if not empty_tag: raise RuntimeError("Warning: For some reason this comment is referenced twice!!:\n\n"+html.tostring(thiscommentreference))
            if prevcomrefsrepd == numcomrefsrepd:
                print(
                    "Warning: I can't find the highlighted text for the comment:\n\n"
                    + html.tostring(thiscommentreference)
                    + "so I'm dropping it"
                )
        else:
            raise RuntimeError("Warning, I couldn't parse this!!")
        numcomrefs += 1
    else:
        print("Warning, found a comment with no text")
print(
    "I found %d comment references and replaced %d"
    % (numcomrefs, numcomrefsrepd)
)
if manual_math_conversion:
    for j in doc.xpath("//sub"):
        thistext = j.text_content()
        # {{{ remove children
        for l in j.getchildren():
            l.drop_tree()
        # }}}
        if len(thistext) > 0:
            if j.tail is None:
                j.tail = ""
            thistail = j.tail
            j.tail = ""
            j.text = (
                "%%ENTERMATHMODE%%_{%s}%%LEAVEMATHMODE%%" % thistext + thistail
            )
            # j.text = '\\ensuremath{_{'+inlineequation_re.sub('\1',j.text)
            # j.tail = inlineequation_re.sub('\1',j.tail)+'}}'
        j.drop_tag()
    for j in doc.xpath("//sup"):
        thistext = j.text_content().encode("utf-8")
        # {{{ remove children
        for l in j.getchildren():
            l.drop_tree()
        # }}}
        if len(thistext) > 0:
            if j.tail is None:
                j.tail = ""
            thistail = str(j.tail)
            j.tail = ""
            j.text = (
                "%%ENTERMATHMODE%%^{%s}%%LEAVEMATHMODE%%" % thistext + thistail
            )
        j.drop_tag()
    # for j in doc.xpath('//*[contains(@class,"cmmi")]'):
    for mathmodefontsize in [7, 8, 12, 81, 121]:
        for mathmodefonttype in ["cmmi", "cmr", "cmsy"]:
            for j in doc.find_class(
                "%s-%d" % (mathmodefonttype, mathmodefontsize)
            ):  # find the math-mode stuff
                thistext = str(unidecode(j.text_content()))
                # {{{ remove children
                for l in j.getchildren():
                    l.drop_tree()
                # }}}
                if len(thistext) > 0:
                    if j.tail is None:
                        j.tail = ""
                    thistail = unidecode(j.tail)
                    j.tail = ""
                    j.text = (
                        "%%ENTERMATHMODE%%%s%%LEAVEMATHMODE%%" % thistext
                        + thistail
                    )
                    # j.text = '\\ensuremath{_{'+inlineequation_re.sub('\1',j.text)
                    # j.tail = inlineequation_re.sub('\1',j.tail)+'}}'
                j.drop_tag()
symbol_lookup = {
    "x": "\\xi ",
    "p": "\\pi",
    "k": "\\kappa",
    "s": "\\sigma",
    "y": "\\psi",
    "h": "\\eta",
    "N": "\\Nu",
    "n": "\\nu",
    "e": "\\epsilon",
    "o": "\\omicron",
    "r": "\\rho",
    " ": " ",
    "_": "_",
    "{": "{",
    "}": "}",
}
for j in doc.find_class("GramE"):
    j.drop_tag()
for j in doc.xpath('//*[contains(@style,"font-family:Symbol")]'):
    newtext = "%ENTERMATHMODE%"
    thistail = str(j.tail)
    j.tail = ""
    thistext = str(j.text)
    k_index = 0
    while k_index < len(thistext):
        k = thistext[k_index]
        while k_index < len(thistext) and k == "\\":
            print("found command")
            print("pass %s\n" % k)
            newtext = newtext + k
            k_index += 1
            k = thistext[k_index]
            while k_index < len(thistext) and k not in [" ", "\\", "{"]:
                # gobble up commands
                print("pass %s\n" % k)
                newtext = newtext + k
                k_index += 1
                k = thistext[k_index]
        try:
            newtext = newtext + symbol_lookup[k]
        except:
            raise ValueError(
                "symbol for symbol font '%s' not found! Open the script and put it in the symbol_lookup dictionary"
                % k
            )
        k_index += 1
    newtext = newtext + "%LEAVEMATHMODE%"
    j.text = newtext + thistail
    j.drop_tag()
# print lsafen(map(html.tostring,newlist),wrap = 60)
newfile = re.sub(r"(.*)(\.htm.*)", r"\1_texcomm\2", sys.argv[1])
fp = open(newfile, "w")
content = html.tostring(doc)
# content = content.replace('$$','')
for mathmodefonttype in ["cmmi", "cmr", "cmsy"]:
    if content.find("class=%s-" % mathmodefonttype) > 0:
        raise ValueError(
            "error, I see a string '%s' which indicates math mode, but apparently you're not searching for the correct font size, so go add the font into the list of math mode font sizes"
            % content[
                content.find("%s-" % mathmodefonttype) : content.find(
                    "%s-" % mathmodefonttype
                )
                + 14
            ]
        )
content_list = list(content)
inmathmode = False
for j in range(0, len(content_list)):
    if content_list[j] == "$":
        if content_list[j - 1] != "\\":
            if inmathmode:
                content_list[j] = "%LEAVEMATHMODE%"
                inmathmode = False
            else:
                content_list[j] = "%ENTERMATHMODE%"
                inmathmode = TRUE
content = "".join(content_list)


# content = content.replace('%ENTERMATHMODE%','$')
# content = content.replace('%LEAVEMATHMODE%','$')
def decodemathmode(arg):
    for j in range(0, 20):
        # just take a couple more passes to be sure
        # arg = re.sub(r'\\ensuremath{(.*)}( *)\\ensuremath{(.*)}',r'\\ensuremath{\1\2\3}',arg)
        arg = re.sub(
            r"([(),\.0-9]*)%LEAVEMATHMODE%([(),\.0-9]*)%ENTERMATHMODE%([(),\.0-9]*)",
            r"\1\2\3",
            arg,
        )
        arg = re.sub(r"_{([^}]*)}_{([^}]*)}", r"_{\1\2}", arg)
        arg = re.sub(r"\^{([^}]*)}\^{([^}]*)}", r"^{\1\2}", arg)
    nextenter = arg.find("%ENTERMATHMODE%")
    while nextenter > 0:
        arg = arg.replace("%ENTERMATHMODE%", "$", 1)
        nextenter = arg.find("%ENTERMATHMODE%")
        nextexit = arg.find("%LEAVEMATHMODE%")
        replaced = True  # just to start the loop
        while replaced:
            if (
                nextenter < nextexit
            ):  # there is a math mode inside this one, so gobble it up
                arg = arg.replace("%ENTERMATHMODE%", "", 1)
                arg = arg.replace("%LEAVEMATHMODE%", "", 1)
                nextenter = arg.find("%ENTERMATHMODE%")
                nextexit = arg.find("%LEAVEMATHMODE%")
                replaced = True
            else:
                arg = arg.replace(
                    "%LEAVEMATHMODE%", "$", 1
                )  # close this math environment
                replaced = False
        nextenter = arg.find("%ENTERMATHMODE%")
        print("next enter is at", nextenter)
    return arg


content = decodemathmode(content)
fp.write(content)
# fp.write('\n'.join(map(html.tostring,newlist)))
fp.close()
fp = open(newfile, "r")
content = fp.read()
fp.close()
textfile = re.sub(r"(.*)(\.htm.*)", r"\1.txt", newfile)
doc = html.fromstring(content)
fp = open(textfile, "w")
fp.write(unidecode(doc.text_content()))
fp.close()
textfile = re.sub(r"(.*)(\.htm.*)", r"\1_comments.tex", newfile)
fp = open(textfile, "w")
fp.write(decodemathmode(comment_file_text).encode("utf-8"))
fp.close()
