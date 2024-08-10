import re, logging, sys, itertools
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
    if thistext[pos] == opener:
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
    except Exception:
        raise RuntimeError(
            "hit end of file without closing a bracket, original error\n"
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
        with open(filename, encoding="utf-8") as fp:
            alltext = fp.read()
        # {{{ determine if the filetype is latex or markdown
        file_extension = filename.split(".")[-1]
        if file_extension == "tex":
            filetype = "latex"
        elif file_extension == "md":
            print("identified as markdown!!")
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
            print("-------------")
            print(alltext[m.start() : m.end()])
            print("-------------")
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
        thispara_split = alltext[para_idx].split('\n')
        if filetype == 'latex':
            line_idx = 0
            while line_idx < len(thispara_split):
                # {{{ exclude section headers and environments
                thisline = thispara_split[line_idx]
                m = re.match(r"\\(?:section|subsection|subsubsection|paragraph|newcommand|input){", thisline)
                if m:
                    starting_line = thisline
                    remaining_in_para = '\n'.join(thispara_split[line_idx:])
                    pos = match_paren(remaining_in_para, m.span()[-1],"{")
                    # to find the closing line, I need to find the line number
                    # inside alltext[para_idx] that corresponds to the character position
                    # pos.  Do this by counting the number of newlines between 
                    # the character len(m.group()) and pos
                    closing_line = (remaining_in_para[m.span()[-1]:pos].count('\n')
                                    + line_idx)
                    exclusion_idx.append((para_idx, starting_line, closing_line))  
                    line_idx = closing_line
                    print("*"*30,"excluding",'*'*30)
                    print(thispara_split[starting_line:closing_line])
                    print("*"*69)
                else:
                    m = re.search(r"\\begin{(equation|align)}", thisline)
                    if m:
                        # exclude everything until the end of the environment
                        # to do this, I need to make a new string that gives
                        # everything from here until the end of alltext[para_idx]
                        notfound = True
                        for closing_idx, closing_line in enumerate(thispara_split[line_idx:]):
                            m_close = re.search(r"\\end{" + m.group(1) + "}", closing_line)
                            if m_close:
                                notfound = False
                                break
                        if notfound:
                            raise RuntimeError("didn't find closing line for environment")
                        exclusion_idx.append((para_idx, line_idx, line_idx+closing_idx))
                        print("*"*30,"excluding env",'*'*30)
                        print(thispara_split[line_idx:closing_idx])
                        print("*"*73)
                        line_idx = line_idx + closing_idx
                line_idx += 1
                # }}}
        elif filetype == 'markdown':
            line_idx = 0
            if para_idx == 0 and line_idx == 0:
                # watch out for yaml header
                print("first line is",thispara_split[line_idx])
                if (thispara_split[line_idx].startswith("---")
                    or thispara_split[line_idx].startswith("...")):
                    starting_line = line_idx
                    j = 1
                    while j < len(thispara_split):
                        if (thispara_split[j].strip() == "---"
                            or thispara_split[j].strip()  == "..."):
                            closing_line = j
                            exclusion_idx.append((para_idx, starting_line, closing_line))
                            print("*" * 30, "excluding yaml header", "*" * 30)
                            print(thispara_split[starting_line:closing_line+1])
                            print("*" * 73)
                            break
                        j += 1
            while line_idx < len(thispara_split):
                thisline = thispara_split[line_idx]
                # {{{ do the same thing for markdown, where I exclude (1) headers (2) figures and (3) tables
                #     written completely with copilot after writing prev!!!
                m = re.match(r"#+\s.*", thisline)  # exclude headers
                if m:
                    exclusion_idx.append((para_idx, line_idx, line_idx))
                    print("*" * 30, "excluding header", "*" * 30)
                    print(thispara_split[line_idx])
                    print("*" * 73)
                else:
                    m = re.search(r"!\[.*\]\(", thisline)  # exclude figures
                    if m:
                        # {{{ find the closing ), as we did for latex commands above
                        remaining_in_para = '\n'.join(thispara_split[line_idx:])
                        pos = match_paren(remaining_in_para, m.span()[-1],"(")
                        closing_line = (remaining_in_para[m.span()[-1]:pos].count('\n')
                                        + line_idx)
                        exclusion_idx.append((para_idx, line_idx, closing_line))
                        line_idx = closing_line
                        print("*" * 30, "excluding figure", "*" * 30)
                        print(alltext[para_idx][starting_line:closing_line+1])
                        print("*" * 73)
                        # }}}
                    else:
                        m = re.search(r"(\|.*\||=\+==|-\+--)", thisline)  # exclude tables
                        if m:
                            starting_line = line_idx
                            m2 = re.search(r"(\|.*\||=\+==|-\+--)", thispara_split[line_idx+1]) # need at least 2 lines
                            if m2:
                                line_idx += 1
                                thisline = thispara_split[line_idx]
                                while in_table:
                                    m = re.search(r"(\|.*\||=\+==|-\+--)", thisline)  # exclude tables
                                    if not m:
                                        break
                                    line_idx += 1
                                exclusion_idx.append((para_idx, starting_line, line_idx))
                            print("*" * 30, "excluding table", "*" * 30)
                            print(alltext[para_idx][starting_line:line_idx+1])
                            print("*" * 73)
                line_idx += 1
                # }}}
    print("all exclusions:",exclusion_idx)
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
        para_lines = [(key, "\n".join([j[1] for j in group]))
                      for key, group in itertools.groupby(para_lines, lambda x: x[0])]
        print("here are the grouped para lines!----------------",para_lines)
        for notexcl, thiscontent in para_lines:
            if notexcl:
                # {{{ here I need a trick to prevent including short abbreviations, etc
                tempsent = re.split(r"([^\.!?]{3}[\.!?])[ \n]", thiscontent)
                for j in tempsent:
                    print("--", j)
                # {{{ put the "separators together with the preceding
                temp_paragraph = []
                for tempsent_num in range(0, len(tempsent), 2):
                    if tempsent_num + 1 < len(tempsent):
                        temp_paragraph.append(
                            tempsent[tempsent_num] + tempsent[tempsent_num + 1]
                        )
                    else:
                        temp_paragraph.append(tempsent[tempsent_num])
                print("-------------------")
                thiscontent = []
                for this_sent in temp_paragraph:
                    thiscontent.extend(
                        re.split(
                            r"(\\(?:begin|end|usepackage|newcommand|section|subsection|subsubsection|paragraph|input){[^}]*})",
                            this_sent,
                        )
                    )
                for this_sent in thiscontent:
                    print("--sentence: ", this_sent)
                # }}}
                # }}}
                for sent_idx in range(len(thiscontent)):  # sentences into words
                    thiscontent[sent_idx] = [
                        word
                        for word in re.split("[ \n]+", thiscontent[sent_idx])
                        if len(word) > 0
                    ]
                para_lines_procd = (True,thiscontent)
            else:
                para_lines_procd = (False,thiscontent)
        alltext[para_idx] = para_lines_procd
    print("*"*50+"\n"+"parsed alltext"+"*"*50)
    print(alltext)
    print('\n\n')
    # {{{ now that it's organized into paragraphs, sentences, and
    #    words, wrap the sentences
    lines = []
    for para_idx in range(len(alltext)):  # paragraph number
        notexcl, para_content = alltext[para_idx]
        if notexcl:
            for residual_sentence in para_content:
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
                    print('-'*10+" here is the residual sentence:\n\t",residual_sentence)
                    lines.append(
                        " " * indentation
                        + " ".join(residual_sentence[: nextline_upto + 1])
                    )
                    residual_sentence = residual_sentence[nextline_upto + 1 :]
                    if indentation == 0:
                        indentation = indent_amount
            lines += [""]  # the extra line break between paragraphs
        else:
            lines += [para_content, ""]
        indentation = 0 # if excluded or new sentence, indentation goes back to zero
    print("here are lines!!\n\n\n\n",lines)
    # }}}
    if filename is None:
        print(("\n".join(lines)))
    else:
        fp = open(filename, "w", encoding="utf-8")
        fp.write(("\n".join(lines)))
        fp.close()
