import re, logging, sys
import numpy as np


def match_paren(thistext, pos, opener="{"):
    closer = {
            "{":"}",
            "(":")",
            "[":"]",
              }[opener]
    if pos == 0:
        raise RuntimeError(
            "can't deal with babel string at the very beginning of the file"
        )
    if thistext[pos] == "{":
        parenlevel = 1
    else:
        raise ValueError("You aren't starting on a curly bracket")
    try:
        while parenlevel > 0:
            pos += 1
            if thistext[pos] == opener:
                if thistext[pos - 1] != "\\":
                    parenlevel += 1
            elif thistext[pos] == closer:
                if thistext[pos - 1] != "\\":
                    parenlevel -= 1
    except Exception as e:
        raise RuntimeError(
            "hit end of file without closing a bracket, original error\n"
            + repr(e)
        )
    return pos

def run(
    filename,
    wrapnumber=45,
    punctuation_slop=20,
    stupid_strip=False,
    indent_amount=4,
):
    # {{{ load the file
    if filename is not None:
        fp = open(filename, encoding="utf-8")
        alltext = fp.read()
        fp.close()
        # {{{ determine if the filetype is latex or markdown
        file_extension = filename.split(".")[-1]
        if file_extension == "tex":
            filetype = "latex"
        elif file_extension == "md":
            filetype = "markdown"
        # }}}
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        fp = sys.stdin
        alltext = fp.read()
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
            stop_bracket = match_paren(alltext, m.start(),"{")
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
            logging.debug("-------------")
            logging.debug(alltext[m.start() : m.end()])
            logging.debug("-------------")
            stop_bracket = match_paren(alltext, m.end() - 1,"{")
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
    exclusion_idx = []
    for para_idx in range(len(alltext)):
        if filetype == 'latex':
            line_idx = 0
            while line_idx < len(alltext[para_idx]):
                # {{{ exclude section headers and environments
                thisline = alltext[para_idx][line_idx]
                m = re.match(r"\\(?:section|subsection|subsubsection|paragraph|newcommand|input){", thisline)
                if m:
                    starting_line = thisline
                    pos = match_paren(alltext[para_idx], m.span()[-1],"{")
                    # to find the closing line, I need to find the line number
                    # inside alltext[para_idx] that corresponds to the character position
                    # pos.  Do this by counting the number of newlines between 
                    # the character len(m.group()) and pos
                    closing_line = (alltext[para_idx][m.span()[-1]:pos].count('\n')
                                    + line_idx)
                    exclusion_idx.append((para_idx, starting_line, closing_line))  
                    line_idx = closing_line + 1
                    print("*"*30,"excluding",'*'*30)
                    print(alltext[para_idx][starting_line:closing_line])
                    print("*"*69)
                else:
                    m = re.search(r"\\begin{(equation|align)}", thisline)
                    if m:
                        # exclude everything until the end of the environment
                        # to do this, I need to make a new string that gives
                        # everything from here until the end of alltext[para_idx]
                        notfound = True
                        for closing_line in alltext[para_idx].split('\n')[line_idx:]:
                            m_close = re.search(r"\\end{" + m.group(1) + "}", closing_line)
                            if m_close:
                                notfound = False
                                break
                        if notfound:
                            raise RuntimeError("didn't find closing line for environment")
                    exclusion_idx.append((para_idx, line_idx, closing_line))
                    print("*"*30,"excluding env",'*'*30)
                    print(alltext[para_idx][starting_line:closing_line])
                    print("*"*73)
                else:
                    line_idx += 1
                # }}}
        elif filetype == 'markdown':
            line_idx = 0
            if para_idx == 0 and line_idx == 0:
                # watch out for yaml header
                if (alltext[para_idx][line_idx].startswith("---")
                    or alltext[para_idx][line_idx].startswith("...")):
                    starting_line = alltext[para_idx][line_idx]
                    line_idx = 0
                    while line_idx < len(alltext[para_idx]):
                        if (alltext[para_idx][line_idx].startswith("---")
                            or alltext[para_idx][line_idx].startswith("...")):
                            closing_line = line_idx
                            exclusion_idx.append((para_idx, starting_line, closing_line))
                            line_idx += 1
                            print("*" * 30, "excluding yaml header", "*" * 30)
                            print(alltext[para_idx][starting_line:closing_line])
                            print("*" * 73)
            while line_idx < len(alltext[para_idx]):
                thisline = alltext[para_idx][line_idx]
                # {{{ do the same thing for markdown, where I exclude (1) headers (2) figures and (3) tables
                #     written completely with copilot after writing prev!!!
                m = re.match(r"#+\s.*", thisline)  # exclude headers
                if m:
                    starting_line = thisline
                    closing_line = line_idx
                    exclusion_idx.append((para_idx, starting_line, closing_line))
                    line_idx += 1
                    print("*" * 30, "excluding header", "*" * 30)
                    print(alltext[para_idx][starting_line:closing_line])
                    print("*" * 73)
                else:
                    m = re.search(r"!\[.*\]\(", thisline)  # exclude figures
                    if m:
                        # {{{ find the closing ), as we did for latex commands above
                        starting_line = thisline
                        pos = match_paren(alltext[para_idx], m.span()[-1], "(")
                        closing_line = (alltext[para_idx][m.span()[-1]:pos].count('\n')
                                        + line_idx)
                        exclusion_idx.append((para_idx, starting_line, closing_line))
                        line_idx = closing_line + 1
                        print("*" * 30, "excluding figure", "*" * 30)
                        print(alltext[para_idx][starting_line:closing_line])
                        print("*" * 73)
                        # }}}
                    else:
                        m = re.match(r"\|.*\|", thisline)  # exclude tables
                        if m:
                            starting_line = thisline
                            closing_line = line_idx
                            exclusion_idx.append((para_idx, starting_line, closing_line))
                            line_idx += 1
                            print("*" * 30, "excluding table", "*" * 30)
                            print(alltext[para_idx][starting_line:closing_line])
                            print("*" * 73)
                        else:
                            line_idx += 1
                # }}}
    for para_idx in range(len(alltext)):  # split paragraphs into sentences
        para_lines = alltext[para_idx].split("\n")
        # list comprehension to grab excluded lines for this paragraph
        excluded_lines = [j[1:] for j in exclusion_idx if j[0] == para_idx]
        # chunk para_lines into a list of tuples, where each tuple is a boolean
        # (False if excluded) and the line itself
        para_lines = [(True, j) for j in para_lines]
        for start_excl, stop_excl in excluded_lines:
            para_lines[start_excl:stop_excl+1] = [(False, j[1])
                                                  for j in para_lines[start_excl:stop_excl+1]]   
        # use join inside a list comprehension to gather contiguous chunks of True
        # and False together
        para_lines = ["\n".join([j[1] for j in group])
                      for key, group in itertools.groupby(para_lines, lambda x: x[0])]
        para_lines_procd = []
        for thisexcl, thiscontent in para_lines:
            if thisexcl:
                para_lines_procd.append((False,thiscontent))
            else:
                # {{{ here I need a trick to prevent including short abbreviations, etc
                tempsent = re.split(r"([^\.!?]{3}[\.!?])[ \n]", thiscontent)
                for j in tempsent:
                    logging.debug("--", j)
                # {{{ put the "separators together with the preceding
                temp_paragraph = []
                for tempsent_num in range(0, len(tempsent), 2):
                    if tempsent_num + 1 < len(tempsent):
                        temp_paragraph.append(
                            tempsent[tempsent_num] + tempsent[tempsent_num + 1]
                        )
                    else:
                        temp_paragraph.append(tempsent[tempsent_num])
                logging.debug("-------------------")
                thiscontent = []
                for this_sent in temp_paragraph:
                    thiscontent.extend(
                        re.split(
                            r"(\\(?:begin|end|usepackage|newcommand|section|subsection|subsubsection|paragraph|input){[^}]*})",
                            this_sent,
                        )
                    )
                for this_sent in thiscontent:
                    logging.debug("--sentence: ", this_sent)
                # }}}
                # }}}
                for sent in range(len(thiscontent)):  # sentences into words
                    thiscontent[sent] = [
                        word
                        for word in re.split("[ \n]+", thiscontent[sent])
                        if len(word) > 0
                    ]
                para_lines_procd.append((True,thiscontent))
        alltext[para_idx] = para_lines_procd
    # {{{ now that it's organized into paragraphs, sentences, and
    #    words, wrap the sentences
    lines = []
    for para_idx in range(len(alltext)):  # paragraph number
        lines += ["\n"]  # the extra line break between paragraphs
        for sent_idx in range(len(alltext[para_idx])):  # sentences into words
            notexcl,residual_sentence = alltext[para_idx][sent_idx]
            indentation = 0 # if excluded or new sentence, indentation goes back to zero
            if notexcl:
                while len(residual_sentence) > 0:
                    numchars = (
                        np.array(list(map(len, residual_sentence))) + 1
                    )  # +1 for space
                    cumsum_num = np.cumsum(numchars)
                    nextline_upto = np.argmin(abs(cumsum_num - wrapnumber))  #
                    #   the next line goes up to this position
                    nextline_punct_upto = np.array(
                        [
                            cumsum_num[j]
                            if (
                                residual_sentence[j][-1]
                                in [",", ";", ":", ")", "-"]
                            )
                            else 10000
                            for j in range(len(residual_sentence))
                        ]
                    )
                    if any(nextline_punct_upto < 10000):
                        nextline_punct_upto = np.argmin(
                            abs(nextline_punct_upto - wrapnumber)
                        )
                        if nextline_punct_upto < nextline_upto:
                            if (
                                nextline_upto - nextline_punct_upto
                                < punctuation_slop
                            ):
                                nextline_upto = nextline_punct_upto
                    lines.append(
                        " " * indentation
                        + " ".join(residual_sentence[: nextline_upto + 1])
                    )
                    residual_sentence = residual_sentence[nextline_upto + 1 :]
                    if indentation == 0:
                        indentation = indent_amount
    # }}}
    if filename is None:
        print(("\n".join(lines)))
    else:
        fp = open(filename, "w", encoding="utf-8")
        fp.write(("\n".join(lines)))
        fp.close()
