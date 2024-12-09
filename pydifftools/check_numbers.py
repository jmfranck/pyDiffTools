from subprocess import Popen, PIPE
import os


def run(arguments):
    try:
        start, stop = list(map(int, arguments))
    except:
        raise ValueError("I didn't understand the arguments" + repr(arguments))
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
            except:
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
