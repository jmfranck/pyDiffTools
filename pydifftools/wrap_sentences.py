import re
import sys
import itertools

from .command_registry import register_command


def match_paren(thistext, pos, opener="{"):
    closerdict = {
        "{": "}",
        "(": ")",
        "[": "]",
        "$$": "$$",
        "~~~": "~~~",
        "<!--": "-->",
    }
    if opener in closerdict.keys():
        closer = closerdict[opener]
    else:
        m = re.match(r"<(\w+)", opener)
        assert m
        closer = "</" + m.groups()[0]
    if thistext[pos : pos + len(opener)] == opener:
        parenlevel = 1
    else:
        raise ValueError(
            f"You aren't starting on a '{opener}':"
            + thistext[:pos]
            + ">>>>>"
            + thistext[pos:]
        )
    while parenlevel > 0 and pos < len(thistext):
        pos += 1
        if thistext[pos : pos + len(closer)] == closer:
            if thistext[pos - 1] != "\\":
                parenlevel -= 1
        elif thistext[pos : pos + len(opener)] == opener:
            if thistext[pos - 1] != "\\":
                parenlevel += 1
    if pos == len(thistext):
        raise RuntimeError(
            f"hit end of file without closing {opener} with {closer}\n"
            "here is the offending text!:\n" + ("=" * 30) + thistext
        )
    return pos


@register_command(
    "wrap with indented sentence format (for markdown or latex).",
    "wrap with indented sentence format (for markdown or latex).\n"
    "Optional flag --cleanoo cleans latex exported from\n"
    "OpenOffice/LibreOffice\n"
    "Optional flag -i # specifies indentation level for subsequent\n"
    "lines of a sentence (defaults to 4 -- e.g. for markdown you\n"
    "will always want -i 0)",
    help={
        "filename": "Input file to wrap. Use '-' to read from stdin.",
        "cleanoo": "Strip LibreOffice markup before wrapping.",
        "i": "Indentation level for wrapped lines.",
    },
)
def wr(filename, wrapnumber=45, punctuation_slop=20, cleanoo=False, i=-1):
    indent_amount = i if i != -1 else 4
    stupid_strip = cleanoo
    if filename == "-":
        filename = None
    # {{{ load the file
    if filename is not None:
        with open(filename, encoding="utf-8") as fp:
            alltext = fp.read()
        # {{{ determine if the filetype is latex or markdown
        file_extension = filename.split(".")[-1]
        if file_extension == "tex":
            filetype = "latex"
        elif file_extension == "md":
            # print("identified as markdown!!")
            filetype = "markdown"
        elif file_extension == "qmd":
            # print("identified as markdown!!")
            filetype = "markdown"
        if filetype == "markdown":
            if i == -1:
                indent_amount = 0
        # }}}
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        fp = sys.stdin
        alltext = fp.read()
        filetype = "latex"
    # }}}
    # {{{ strip stupid commands that appear in openoffice conversion
    if stupid_strip:
        alltext = re.sub(r"\\bigskip\b\s*", "", alltext)
        alltext = re.sub(r"\\;", "", alltext)
        alltext = re.sub(r"(?:\\ ){4}", r"\quad ", alltext)
        alltext = re.sub(r"\\ ", " ", alltext)
        # alltext = re.sub('\\\\\n',' ',alltext)
        # {{{ remove select language an accompanying bracket
        m = re.search(r"{\\selectlanguage{english}", alltext)
        while m:
            stop_bracket = match_paren(alltext, m.start(), "{")
            alltext = (
                alltext[: m.start()]
                + alltext[m.end() : stop_bracket]
                + alltext[stop_bracket + 1 :]
            )  # pos is the position of
            #                         the matching curly bracket
            m = re.search(r"{\\selectlanguage{english}", alltext)
        # }}}
        # {{{ remove the remaining select languages
        m = re.search(r"\\selectlanguage{english}", alltext)
        while m:
            alltext = alltext[: m.start()] + alltext[m.end() :]
            m = re.search(r"\\selectlanguage{english}", alltext)
        # }}}
        # {{{ remove mathit
        m = re.search(r"\\mathit{", alltext)
        while m:
            # print("-------------")
            # print(alltext[m.start() : m.end()])
            # print("-------------")
            stop_bracket = match_paren(alltext, m.end() - 1, "{")
            alltext = (
                alltext[: m.start()]
                + alltext[m.end() : stop_bracket]
                + alltext[stop_bracket + 1 :]
            )  # pos is the position of
            #                         the matching curly bracket
            m = re.search(r"\\mathit{", alltext)
        # }}}
    # }}}
    alltext = alltext.split("\n\n")  # split paragraphs
    # interleave with blank strings that get turned into double newlines
    alltext = [k for l_inner in [[j, ""] for j in alltext] for k in l_inner]
    exclusion_idx = []
    for para_idx in range(len(alltext)):
        thispara_split = alltext[para_idx].split("\n")
        if filetype == "latex":
            line_idx = 0
            while line_idx < len(thispara_split):
                # {{{ exclude section headers and environments
                thisline = thispara_split[line_idx]
                m = re.match(
                    r"\\(?:section|subsection|subsubsection|paragraph|"
                    + "newcommand|input){",
                    thisline,
                )
                if m:
                    starting_line = thisline
                    remaining_in_para = "\n".join(thispara_split[line_idx:])
                    pos = match_paren(remaining_in_para, m.span()[-1], "{")
                    # to find the closing line, I need to find the line number
                    # inside alltext[para_idx] that corresponds to the
                    # character position pos.  Do this by counting the number
                    # of newlines between the character len(m.group()) and pos
                    closing_line = (
                        remaining_in_para[m.span()[-1] : pos].count("\n")
                        + line_idx
                    )
                    exclusion_idx.append(
                        (para_idx, starting_line, closing_line)
                    )
                    line_idx = closing_line
                    # print("*" * 30, "excluding", "*" * 30)
                    # print(thispara_split[starting_line:closing_line])
                    # print("*" * 69)
                else:
                    m = re.search(r"\\begin{(equation|align)}", thisline)
                    if m:
                        # exclude everything until the end of the environment
                        # to do this, I need to make a new string that gives
                        # everything from here until the end of
                        # alltext[para_idx]
                        notfound = True
                        for closing_idx, closing_line in enumerate(
                            thispara_split[line_idx:]
                        ):
                            m_close = re.search(
                                r"\\end{" + m.group(1) + "}", closing_line
                            )
                            if m_close:
                                notfound = False
                                break
                        if notfound:
                            raise RuntimeError(
                                "didn't find closing line for environment"
                            )
                        exclusion_idx.append(
                            (para_idx, line_idx, line_idx + closing_idx)
                        )
                        # print("*" * 30, "excluding env", "*" * 30)
                        # print(thispara_split[line_idx:closing_idx])
                        # print("*" * 73)
                        line_idx = line_idx + closing_idx
                line_idx += 1
                # }}}
        elif filetype == "markdown":
            line_idx = 0
            if para_idx == 0 and line_idx == 0:
                # watch out for yaml header
                # print("first line is", thispara_split[line_idx])
                if thispara_split[line_idx].startswith(
                    "---"
                ) or thispara_split[line_idx].startswith("..."):
                    starting_line = line_idx
                    j = 1
                    while j < len(thispara_split):
                        if (
                            thispara_split[j].strip() == "---"
                            or thispara_split[j].strip() == "..."
                        ):
                            closing_line = j
                            exclusion_idx.append(
                                (para_idx, starting_line, closing_line)
                            )
                            break
                        j += 1
            while line_idx < len(thispara_split):
                thisline = thispara_split[line_idx]
                # {{{ do the same thing for markdown, where I exclude (1)
                #     headers (2) figures and (3) tables (4) font
                m = re.match(r"#+\s.*", thisline)  # exclude headers
                if m:
                    exclusion_idx.append((para_idx, line_idx, line_idx))
                    # print("*" * 30, "excluding header", "*" * 30)
                    # print(thispara_split[line_idx])
                    # print("*" * 73)
                else:
                    m = re.search(r"!\[.*\]\(", thisline)  # exclude figures
                    if m:
                        # {{{ find the closing ), as we did for latex commands
                        #     above
                        remaining_in_para = "\n".join(
                            thispara_split[line_idx:]
                        )
                        pos = match_paren(
                            remaining_in_para, m.span()[-1] - 1, "("
                        )
                        closing_line = (
                            remaining_in_para[m.span()[-1] : pos].count("\n")
                            + line_idx
                        )
                        exclusion_idx.append(
                            (para_idx, line_idx, closing_line)
                        )
                        line_idx = closing_line
                        # }}}
                    else:
                        m = re.search(
                            r"(\|.*\||=\+==|-\+--)", thisline
                        )  # exclude tables
                        if m:
                            starting_line = line_idx
                            m2 = re.search(
                                r"(\|.*\||=\+==|-\+--)",
                                thispara_split[line_idx + 1],
                            )  # need at least 2 lines
                            if m2:
                                while True:
                                    line_idx += 1
                                    if line_idx > len(thispara_split) - 1:
                                        line_idx -= 1
                                        break
                                    thisline = thispara_split[line_idx]
                                    m = re.search(
                                        r"(\|.*\||=\+==|-\+--)", thisline
                                    )
                                    if not m:
                                        line_idx -= 1
                                        break
                                exclusion_idx.append(
                                    (para_idx, starting_line, line_idx)
                                )
                                # print("*" * 30, "excluding table", "*" * 30)
                                # print(
                                #    thispara_split[
                                #        starting_line : line_idx + 1
                                #    ]
                                # )
                                # print("*" * 73)
                        else:
                            m = re.search(
                                r"\$\$", thisline
                            )  # exclude equations
                            if m:
                                starting_line = line_idx
                                # {{{ find the closing $$, as we did for latex
                                #     commands above
                                remaining_in_para = "\n".join(
                                    thispara_split[line_idx:]
                                )
                                pos = match_paren(
                                    remaining_in_para, m.span()[-1] - 2, "$$"
                                )
                                closing_line = (
                                    remaining_in_para[
                                        m.span()[-1] : pos
                                    ].count("\n")
                                    + line_idx
                                )
                                exclusion_idx.append(
                                    (para_idx, line_idx, closing_line)
                                )
                                line_idx = closing_line
                                # }}}
                            else:
                                m = re.search(
                                    r"^~~~", thisline
                                )  # exclude equations
                                if m:
                                    starting_line = line_idx
                                    # {{{ find the closing $$, as we did for
                                    #     latex commands above
                                    remaining_in_para = "\n".join(
                                        thispara_split[line_idx:]
                                    )
                                    pos = match_paren(
                                        remaining_in_para, m.span()[0], "~~~"
                                    )
                                    closing_line = (
                                        remaining_in_para[
                                            m.span()[-1] : pos
                                        ].count("\n")
                                        + line_idx
                                    )
                                    exclusion_idx.append(
                                        (para_idx, line_idx, closing_line)
                                    )
                                    line_idx = closing_line
                                    # }}}
                                else:
                                    m = re.search(
                                        r"<(\w+) ?.*>", thisline
                                    )  # exclude things enclosed in tags
                                    if m:
                                        starting_line = line_idx
                                        # {{{ find the closing $$, as we did
                                        #     for latex commands above
                                        remaining_in_para = "\n".join(
                                            thispara_split[line_idx:]
                                        )
                                        pos = match_paren(
                                            remaining_in_para,
                                            m.span()[0],
                                            "<" + m.groups()[0],
                                        )
                                        closing_line = (
                                            remaining_in_para[
                                                m.span()[-1] : pos
                                            ].count("\n")
                                            + line_idx
                                        )
                                        exclusion_idx.append(
                                            (para_idx, line_idx, closing_line)
                                        )
                                        line_idx = closing_line
                                        # }}}
                line_idx += 1
                # }}}
    # print("all exclusions:", exclusion_idx)
    all_text_procd = []
    for para_idx in range(len(alltext)):  # split paragraphs into sentences
        para_lines = alltext[para_idx].split("\n")
        # list comprehension to grab excluded lines for this paragraph
        excluded_lines = [j[1:] for j in exclusion_idx if j[0] == para_idx]
        # chunk para_lines into a list of tuples, where each tuple is a boolean
        # (False if excluded) and the line itself
        para_lines = [(True, j) for j in para_lines]
        for start_excl, stop_excl in excluded_lines:
            para_lines[start_excl : stop_excl + 1] = [
                (False, j[1]) for j in para_lines[start_excl : stop_excl + 1]
            ]
        # use join inside a list comprehension to gather contiguous chunks of
        # True and False together
        para_lines = [
            (key, "\n".join([j[1] for j in group]))
            for key, group in itertools.groupby(para_lines, lambda x: x[0])
        ]
        # print("here are the grouped para lines!----------------", para_lines)
        for notexcl, thiscontent in para_lines:
            if notexcl:
                # {{{ here I need a trick to prevent including short
                #     abbreviations, etc
                tempsent = re.split(r"([^\.!?]{3}[\.!?])[ \n]", thiscontent)
                # for j in tempsent:
                #    #rint("--", j)
                # {{{ put the "separators together with the preceding
                temp_paragraph = []
                for tempsent_num in range(0, len(tempsent), 2):
                    if tempsent_num + 1 < len(tempsent):
                        temp_paragraph.append(
                            tempsent[tempsent_num] + tempsent[tempsent_num + 1]
                        )
                    else:
                        temp_paragraph.append(tempsent[tempsent_num])
                # print("-------------------")
                thiscontent = []
                for this_sent in temp_paragraph:
                    thiscontent.extend(
                        re.split(
                            r"(\\(?:begin|end|usepackage|newcommand|section"
                            + "|subsection|subsubsection|paragraph"
                            + "|input){[^}]*})",
                            this_sent,
                        )
                    )
                # for this_sent in thiscontent:
                #    #rint("--sentence: ", this_sent)
                # }}}
                # }}}
                for sent_idx in range(
                    len(thiscontent)
                ):  # sentences into words
                    thiscontent[sent_idx] = [
                        word
                        for word in re.split("[ \n]+", thiscontent[sent_idx])
                        if len(word) > 0
                    ]
                if len(thiscontent) == 1 and len(thiscontent[0]) == 0:
                    all_text_procd += [(True, [[""]])]
                else:
                    all_text_procd += [(True, thiscontent)]
            else:
                all_text_procd += [(False, thiscontent)]
    alltext = all_text_procd
    # print("*" * 50 + "\n" + "parsed alltext" + "*" * 50)
    # print(alltext)
    # print("\n\n")
    # {{{ now that it's organized into paragraphs, sentences, and
    #    words, wrap the sentences
    lines = []
    indentation = 0
    for para_idx in range(len(alltext)):  # paragraph number
        notexcl, para_content = alltext[para_idx]
        if notexcl:
            for residual_sentence in para_content:
                if residual_sentence == [""]:
                    indentation = 0
                    lines.append("")
                    continue
                if filetype == "latex":
                    indentation = 0
                while len(residual_sentence) > 0:
                    # Compute cumulative character counts without relying on
                    # numpy.
                    numchars = [len(word) + 1 for word in residual_sentence]
                    cumsum_num = []
                    running_total = 0
                    for num in numchars:
                        running_total += num
                        cumsum_num.append(running_total)
                    nextline_upto = min(
                        range(len(cumsum_num)),
                        key=lambda j: abs(cumsum_num[j] - wrapnumber),
                    )
                    nextline_punct_upto = []
                    for j, word in enumerate(residual_sentence):
                        if (
                            word[-1] in [",", ";", ":", ")", "-"]
                            and len(word) > 1
                        ):
                            nextline_punct_upto.append(cumsum_num[j])
                        else:
                            nextline_punct_upto.append(10000)
                    if any(value < 10000 for value in nextline_punct_upto):
                        nextline_punct_upto = min(
                            range(len(nextline_punct_upto)),
                            key=lambda j: abs(
                                nextline_punct_upto[j] - wrapnumber
                            ),
                        )
                        if nextline_punct_upto < nextline_upto:
                            if (
                                nextline_upto - nextline_punct_upto
                                < punctuation_slop
                            ):
                                nextline_upto = nextline_punct_upto
                    # print(
                    #    "-" * 10 + " here is the residual sentence:\n\t",
                    #    residual_sentence,
                    # )
                    lines.append(
                        " " * indentation
                        + " ".join(residual_sentence[: nextline_upto + 1])
                    )
                    residual_sentence = residual_sentence[nextline_upto + 1 :]
                    if indentation == 0:
                        indentation = indent_amount
        else:
            lines += [para_content]
        indentation = (
            0  # if excluded or new sentence, indentation goes back to zero
        )
    # print("here are lines!!\n\n\n\n", lines)
    # }}}
    if filename is None:
        print("\n".join(lines))
    else:
        fp = open(filename, "w", encoding="utf-8")
        fp.write("\n".join(lines))
        fp.close()
