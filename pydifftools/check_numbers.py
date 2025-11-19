from subprocess import Popen, PIPE
import os

from .command_registry import register_command


@register_command(
    "check numbers in a latex catalog (e.g. of numbered notebook) of items of"
    " the form '\\item[anything number.anything]'",
    help={
        "start": "First number in the range to search",
        "stop": "Last number in the range to search",
    },
)
def num(start, stop):
    """Search a range of numbers in notebook list files and report matches."""

    try:
        start = int(start)
        stop = int(stop)
    except Exception:
        raise ValueError(
            "I didn't understand the arguments" + repr([start, stop])
        )
    for thisnumber in range(start, stop + 1):
        if os.name == "posix":
            result = Popen(
                [r'grep -Rice "%d\." ~/notebook/list*' % thisnumber],
                shell=True,
                stdout=PIPE,
            )
        else:
            try:
                result = Popen(
                    [
                        r"C:\Program Files\Git\bin\bash.exe",
                        "-c",
                        r'grep -rice "%d\." ~/notebook/list*' % thisnumber,
                    ],
                    stdout=PIPE,
                )
            except Exception:
                result = Popen(
                    [
                        r"C:\Program Files (x86)\Git\bin\bash.exe",
                        "-c",
                        r'grep -rice "%d\." ~/notebook/list*' % thisnumber,
                    ],
                    stdout=PIPE,
                )
        matched_already = False
        matched_multiple = False
        full_string = []
        for thisline in result.stdout.readlines():
            if (not thisline.find(":0") > -1) and thisline.find(".tex:") > -1:
                if not matched_already:
                    print(thisnumber, " ", end=" ")
                if not thisline.find(":1") > -1:
                    matched_already = True
                full_string.append(thisline.strip())
                if matched_already:  # more than one match
                    print("conflicting files:")
                    print("\n".join(full_string))
                    matched_multiple = True
                matched_already = True
        if not matched_multiple:
            if matched_already:
                print("single\t\t", full_string[-1][:-2])
            else:
                print(thisnumber, " has no match")
