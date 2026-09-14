from difflib import SequenceMatcher
from bisect import bisect_right
import math
from .wrap_sentences import (
    classify_lines,
    markdown_blocks,
    wrap_blocks,
    wrap_prose,
)


def run(arguments):
    with open(arguments[0], encoding="utf-8") as fp:
        text1 = fp.read()
    # text1 = text1.decode('utf-8')
    fp = open(arguments[1], encoding="utf-8")
    text2 = fp.read()
    fp.close()
    filetype = (
        "markdown" if arguments[1].endswith((".md", ".qmd")) else "latex"
    )
    if filetype == "markdown":
        result = match_blocks(markdown_blocks(text1), markdown_blocks(text2))
    else:
        result = match_text(text1, text2, filetype)
    with open(arguments[1], "w", encoding="utf-8") as fp:
        fp.write(result)


def match_blocks(old, new, width=80):
    """Match container bodies without treating markers as words."""
    output = []
    matcher = SequenceMatcher(
        None, [b.kind for b in old], [b.kind for b in new]
    )
    for operation, a, b, c, d in matcher.get_opcodes():
        if operation == "equal":
            for reference, target in zip(old[a:b], new[c:d]):
                if target.kind == "raw" or reference.text == target.text:
                    output.append(target.text)
                elif target.children:
                    output.append(
                        target.restore(
                            match_blocks(
                                reference.children,
                                target.children,
                                max(1, width - target.margin),
                            )
                        )
                    )
                else:
                    output.append(
                        match_text(
                            reference.text, target.text, "markdown", width
                        )
                    )
        else:
            output.append(wrap_blocks(new[c:d], width))
    return "".join(output)


def match_text(text1, text2, filetype, fallback_width=80):
    """Reuse reference whitespace and wrap overflowing edits in plain text."""
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
                j += 1
            else:  # it's a word
                retval_words.append(input_tokens[j])
                if input_iswhitespace[j + 1]:
                    retval_whitespace.append(input_tokens[j + 1])
                    j += 2
                else:
                    # Either token can contain a newline combination.
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
    # {{{ locate reference prose and protected target text
    reference_lines = classify_lines(text1, filetype)
    reference_starts = []
    position = 0
    for _, line in reference_lines:
        reference_starts.append(position)
        position += len(line)
    word_starts = [0]
    for word, whitespace in zip(text1_words, text1_whitespace):
        word_starts.append(word_starts[-1] + len(word) + len(whitespace))
    target_protected = []
    position = 0
    for allowed, line in classify_lines(text2, filetype):
        if not allowed:
            target_protected.append((position, position + len(line)))
        position += len(line)
    target_word_starts = [0]
    for word, whitespace in zip(text2_words, text2_whitespace):
        target_word_starts.append(
            target_word_starts[-1] + len(word) + len(whitespace)
        )
    edits = []
    protected_output = []
    # }}}
    for j in diffs:
        output_start = len(final_text)
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
            # {{{ reuse original double newlines
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
                # Otherwise, reuse newline positions from the old text.
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
        if j[0] != "equal":
            reference_line = max(
                0, bisect_right(reference_starts, word_starts[j[1]]) - 1
            )
            edits.append((output_start, len(final_text), reference_line))
        if j[0] != "delete":
            position = output_start
            for k, (word, space) in enumerate(zip(temp_addition, whitespace)):
                target = j[3] + k
                if any(
                    start < target_word_starts[target + 1]
                    and stop > target_word_starts[target]
                    for start, stop in target_protected
                ):
                    protected_output.append(
                        (position, position + len(word) + len(space))
                    )
                position += len(word) + len(space)
    # {{{ wrap only changed prose lines that clearly exceed the local width
    output = []
    position = 0
    for allowed, line in classify_lines(final_text, filetype):
        stop = position + len(line)
        nearby_edits = [
            reference
            for start, end, reference in edits
            if start < stop and end >= position
        ]
        protected = any(
            start < stop and end > position for start, end in protected_output
        )
        if allowed and line.strip() and nearby_edits and not protected:
            reference = nearby_edits[0]
            nearby = sorted(
                (
                    idx
                    for idx, (can_wrap, source) in enumerate(reference_lines)
                    if can_wrap and source.strip()
                ),
                key=lambda idx: (abs(idx - reference), idx),
            )[:10]
            widths = sorted(
                len(reference_lines[idx][1].rstrip("\n")) for idx in nearby
            )
            width = (
                widths[math.ceil(0.75 * len(widths)) - 1]
                if len(widths) >= 2
                else fallback_width
            )
            if len(line.rstrip("\n")) > 1.5 * width:
                indentation = ""
                for idx in nearby:
                    source = reference_lines[idx][1]
                    prefix = source[: len(source) - len(source.lstrip(" \t"))]
                    if prefix:
                        indentation = prefix
                        break
                prefix = line[: len(line) - len(line.lstrip(" \t"))]
                wrapped = wrap_prose(
                    line[len(prefix) :],
                    width,
                    filetype=filetype,
                    indent_amount=len(indentation.expandtabs()),
                )
                line = prefix + wrapped
        output.append(line)
        position = stop
    final_text = "".join(output)
    # }}}
    return final_text
