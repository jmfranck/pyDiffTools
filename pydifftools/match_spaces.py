from difflib import SequenceMatcher


def run(arguments):
    with open(arguments[0], encoding="utf-8") as fp:
        text1 = fp.read()
    # text1 = text1.decode('utf-8')
    fp = open(arguments[1], encoding="utf-8")
    text2 = fp.read()
    fp.close()
    # text2 = text2.decode('utf-8')
    utf_char = "\u00a0"  # unicode no break space
    text2 = text2.replace(utf_char, " ")  # replace it
    utf_char = "\u2004"  # three-per-em space
    text2 = text2.replace(utf_char, " ")  # replace it

    def parse_whitespace(s):
        retval = []
        white_or_not = []
        current_string = ""
        is_whitespace = True
        for j in s:
            if j in [" ", "\t", "\r", "\n"]:
                if not is_whitespace:
                    retval.append(current_string)
                    white_or_not.append(
                        False
                    )  # I have switched to whitespace, I was not whitespace
                    current_string = j
                else:
                    current_string += j
                is_whitespace = True
            else:
                if is_whitespace and len(retval) > 0:
                    retval.append(current_string)
                    if current_string.count("\n") > 1:
                        white_or_not.append(
                            False
                        )  # double newline is not "whitespace"
                    else:
                        white_or_not.append(True)
                    current_string = j
                else:
                    current_string += j
                is_whitespace = False
        retval.append(current_string)
        white_or_not.append(is_whitespace)
        if is_whitespace and current_string.count("\n") > 1:
            white_or_not.append(False)  # double newline is not "whitespace"
        else:
            white_or_not.append(is_whitespace)
        return retval, white_or_not

    # print zip(*tuple(parse_whitespace(text1)))
    # print zip(*tuple(parse_whitespace(text2)))

    tokens, iswhitespace = parse_whitespace(text1)

    def generate_word_lists(input_tokens, input_iswhitespace):
        retval_words = []
        retval_whitespace = []
        retval_isdoublenewline = []
        j = 0
        # go through and add whitespace and words, always in pairs
        while j < len(input_tokens):
            if input_iswhitespace[j]:
                # make it so the whitespace always comes "after" the word
                retval_words.append("")
                retval_whitespace.append(input_tokens[j])
                j += 1
            elif j == len(input_tokens) - 1:
                # this is the last one, so just add it
                retval_words.append(input_tokens[j])
                retval_whitespace.append("")
                retval_isdoublenewline.append(False)
            else:  # it's a word
                retval_words.append(input_tokens[j])
                if input_iswhitespace[j + 1]:
                    retval_whitespace.append(input_tokens[j + 1])
                    j += 2
                else:
                    # this can happen if it's a newline combo or followed by a newline combo
                    # print repr(input_tokens[j]),'is not followed by whitespace but by',repr(input_tokens[j+1])
                    retval_whitespace.append("")
                    j += 1
                if retval_words[-1].count("\n") > 1:  # double newline
                    retval_isdoublenewline.append(True)
                else:
                    retval_isdoublenewline.append(False)
        return retval_words, retval_whitespace, retval_isdoublenewline

    text1_words, text1_whitespace, text1_isdoublenewline = generate_word_lists(
        tokens, iswhitespace
    )
    # print "-------------------"
    # print "align words only with words and whitespace"
    # print zip(text1_words, text1_words_and_whitespace)
    # print "-------------------"

    tokens, iswhitespace = parse_whitespace(text2)
    text2_words, text2_whitespace, text2_isdoublenewline = generate_word_lists(
        tokens, iswhitespace
    )

    s = SequenceMatcher(None, text1_words, text2_words)
    diffs = s.get_opcodes()
    # print diffs
    final_text = ""
    newline_debt = 0
    last_indent = ""
    for j in diffs:
        if j[0] == "equal":
            temp_addition = text1_words[j[1] : j[2]]
            whitespace = text1_whitespace[j[1] : j[2]]
            for k in range(len(temp_addition)):
                final_text += temp_addition[k] + whitespace[k]
                idx = whitespace[k].find("\n")
                if idx > -1:
                    last_indent = whitespace[k][idx + 1 :]
            if (
                j[2] - j[1] > 4
            ):  # if five or more words have matched, forgive my newline debt
                newline_debt = 0
        elif j[0] == "delete":
            if (
                sum(
                    [
                        thisstr.count("\n")
                        for thisstr in text1_whitespace[j[1] : j[2]]
                    ]
                )
                > 0
            ):
                newline_debt += 1
            # print "delete -- newline debt is now",newline_debt
        elif j[0] == "replace":
            print("newline debt", newline_debt)
            newline_debt += sum(
                [
                    thisstr.count("\n")
                    for thisstr in text1_whitespace[j[1] : j[2]]
                ]
            )
            # print "replace -- newline debt is now",newline_debt
            print(
                "about to replace",
                repr(text1_words[j[1] : j[2]]).encode("unicode-escape"),
            )
            print(
                "   with",
                repr(text2_words[j[3] : j[4]]).encode("unicode-escape"),
            )
            print(
                "   whitepace from ",
                repr(text1_whitespace[j[1] : j[2]]).encode("unicode-escape"),
            )
            oldver_whitespace = text1_whitespace[j[1] : j[2]]
            print(
                "   whitepace to ",
                repr(text2_whitespace[j[3] : j[4]]).encode("unicode-escape"),
            )
            print("   newline debt", newline_debt)
            temp_addition = text2_words[j[3] : j[4]]
            # {{{ check to see if I am adding any double newlines -- if I am use the original version
            temp_isdoublenewline = text2_isdoublenewline[j[3] : j[4]]
            tstdbl_i = 0
            tstdbl_j = 0
            while tstdbl_i < len(temp_isdoublenewline):
                if temp_isdoublenewline[tstdbl_i]:
                    matched = False
                    while (
                        tstdbl_j < len(text1_isdoublenewline[j[1] : j[2]])
                        and not matched
                    ):
                        if text1_isdoublenewline[j[1] : j[2]][tstdbl_j]:
                            temp_addition[tstdbl_i] = text1_words[j[1] : j[2]][
                                tstdbl_j
                            ]
                            matched = True
                        tstdbl_j += 1
                tstdbl_i += 1
            # }}}
            newver_whitespace = text2_whitespace[j[3] : j[4]]
            whitespace = [
                " " if len(x) > 0 else "" for x in newver_whitespace
            ]  # sometimes, the "whitespace" can be nothing
            if newline_debt > 0:
                for k in range(len(temp_addition)):
                    if newver_whitespace[k].count("\n") > 0:
                        whitespace[k] = "\n" + last_indent
                        newline_debt -= whitespace[k].count(
                            "\n"
                        )  # shouldn't be more than one but doesn't hurt
                        if newline_debt < 1:
                            break
                # if I can't make up for the whitespace with the new text, but it where it went in the old text
                for k in range(min(len(oldver_whitespace), len(whitespace))):
                    if oldver_whitespace[k].count("\n") > 0:
                        whitespace[k] = oldver_whitespace[k]
                        newline_debt -= whitespace[k].count(
                            "\n"
                        )  # shouldn't be more than one but doesn't hurt
                        if newline_debt < 1:
                            break
            print("   whitepace became", repr(whitespace))
            for k in range(len(temp_addition)):
                final_text += temp_addition[k] + whitespace[k]
                idx = whitespace[k].find("\n")
                if idx > -1:
                    last_indent = whitespace[k][idx + 1 :]
        elif j[0] == "insert":
            temp_addition = text2_words[j[3] : j[4]]
            newver_whitespace = text2_whitespace[j[3] : j[4]]
            whitespace = [
                " " if len(x) > 0 else "" for x in newver_whitespace
            ]  # sometimes, the "whitespace" can be nothing
            if newline_debt > 0:
                for k in range(len(temp_addition)):
                    if newver_whitespace[k].count("\n") > 0:
                        whitespace[k] = "\n" + last_indent
                        newline_debt -= whitespace[k].count(
                            "\n"
                        )  # shouldn't be more than one but doesn't hurt
                        if newline_debt < 1:
                            break
            for k in range(len(temp_addition)):
                final_text += temp_addition[k] + whitespace[k]
                idx = whitespace[k].find("\n")
                if idx > -1:
                    last_indent = whitespace[k][idx + 1 :]
        else:
            raise ValueError("unknown opcode" + j[0])
    fp = open(arguments[1], "w", encoding="utf-8")
    fp.write(final_text)
    fp.close()
