def comment_definition(commandname, name, comment_text):
    return r"\newcommand{\%s}{%s}" % (commandname, comment_text) + "\n"


def generate_alphabetnumber(x):
    if x < 26:
        return chr(ord("a") + x)
    else:
        higher_places = x // 26
        return generate_alphabetnumber(
            higher_places - 1
        ) + generate_alphabetnumber(x - higher_places * 26)


def matchingbrackets(content, startpoint, bracket_type):
    if bracket_type == "(":
        opening = "("
        closing = ")"
    elif bracket_type == "[":
        opening = "["
        closing = "]"
    elif bracket_type == "{":
        opening = "{"
        closing = "}"
    else:
        raise ValueError("I didn't understand the type of bracket!")
    first = (
        False  # of course, don't want to break until we've found at least one
    )
    level = 0
    for j in range(startpoint, len(content)):
        if content[j] == opening:
            if level == 0:
                first = j
            level += 1
        if content[j] == closing:
            level -= 1
        if level == 0 and first:
            return first, j
