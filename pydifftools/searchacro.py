import re
import os
from pathlib import Path


def replace_acros(pathtofile):
    clean_unused = False
    if pathtofile.parent.resolve() == Path.cwd():
        clean_unused = True
        print(
            "I'm going to clean out the unused acronyms, since myacronyms.sty lives in the current directory"
        )
    else:
        print(pathtofile.parent, "not equal to", Path.cwd())
    acro_restr = r"\\newacronym(?:\[[^\[\]]*\])?{(\w+)}{(\w+)}{.*}"
    acro_re = re.compile(acro_restr)
    regex_replacements = []
    with open(pathtofile, "r", encoding="utf-8") as fp:
        for line in fp:
            m = acro_re.match(line)
            if m:
                inside, toreplace = m.groups()
                regex_replacements.append(
                    (r"\b" + toreplace + r"\b", r"\\gls{" + inside + "}")
                )
                regex_replacements.append(
                    (r"\b" + toreplace + r"s\b", r"\\glspl{" + inside + "}")
                )

    def replace_in_files(regex_replacements, exclude=[pathtofile, "ms.tex"]):
        """
        This function will replace all occurences of specified regex patterns with their corresponding replacements in all .tex files in the current directory except for the file specified in 'exclude'.
        It returns a list of unused regex patterns.
        """
        # Get the current working directory
        directory = os.getcwd()

        unused_patterns = set(regex for regex, _ in regex_replacements)

        # Loop over all files in the directory
        for filename in os.listdir(directory):
            # Only operate on .tex files and exclude the specified file
            if filename.endswith(".tex") and filename not in exclude:
                filepath = os.path.join(directory, filename)
                with open(filepath, "r", encoding="utf-8") as file:
                    filedata = file.read()

                # Perform the replacements
                for regex, replacement in regex_replacements:
                    if re.search(regex, filedata):
                        filedata = re.sub(regex, replacement, filedata)
                        unused_patterns.discard(regex)
                    elif re.search(replacement, filedata):
                        unused_patterns.discard(regex)
                    elif re.search(
                        replacement.replace("gls", "Gls"), filedata
                    ):
                        unused_patterns.discard(regex)
                filedata = re.sub(r"(\.\s*\n\s*)\\gls", r"\1\\Gls", filedata)
                # Write the file out again
                with open(filepath, "w", encoding="utf-8") as file:
                    file.write(filedata)
        return list(unused_patterns)

    unused = replace_in_files(regex_replacements)
    print("unused acronyms:", unused)
    if clean_unused:
        # {{{ get rid of unused
        with open(pathtofile, "r", encoding="utf-8") as fp:
            filedata = fp.read()
        for regex in unused:
            fullreg = r"\\newacronym{(\w+)}{" + regex + "}{.*}"
            if re.search(fullreg, filedata):
                filedata = re.sub(fullreg, "", filedata)
            else:
                raise ValueError("couldn't find", fullreg)
        filedata = re.sub("\n+", "\n", filedata)
        with open(pathtofile, "w", encoding="utf-8") as file:
            file.write(filedata)
        # }}}
