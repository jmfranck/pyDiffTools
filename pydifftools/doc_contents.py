from collections import OrderedDict
import re
from fuzzywuzzy import fuzz


class doc_contents_class(object):
    def __init__(self, format_type="latex"):
        self.contents = OrderedDict()
        self.contents["header"] = ""
        self.types = {}
        self.types["header"] = "header"
        self._aliases = {}
        self._processed_titles = []
        self.set_format(format_type)

    def set_format(self, format_type):
        if format_type == "markdown":
            # markdown levels go deeper, so include subparagraph mapping
            self.level_numbers = {
                "section": 1,
                "subsection": 2,
                "subsubsection": 3,
                "paragraph": 4,
                "subparagraph": 5,
            }
        else:
            # default to latex behavior
            self.level_numbers = {
                "section": 1,
                "subsection": 2,
                "subsubsection": 3,
                "paragraph": 4,
                "subparagraph": 5,
            }
        # map indentation back to section type for outline parsing
        self.inv_prefix = {
            (level - 1) * "\t": section
            for section, level in self.level_numbers.items()
        }
        self.format_type = format_type

    def start_sec(self, thistype, thistitle):
        assert thistitle not in self.contents.keys(), (
            "more than one section with the name:\n" + thistitle
        )
        self.contents[thistitle] = ""
        self.types[thistitle] = thistype
        print("added", thistitle)

    def __setstate__(self, d):
        "set the info from a pickle"
        self.contents = d["contents"]
        self.types = d["types"]
        self._aliases = {}  # doesn't exist, but still needed
        self._processed_titles = []
        if "format_type" in d:
            self.set_format(d["format_type"])
        else:
            self.set_format("latex")
        return

    def __getstate__(self):
        "return info for a pickle"
        return {
            "contents": self.contents,
            "types": self.types,
            "format_type": self.format_type,
        }

    def __iadd__(self, value):
        self.contents[next(reversed(self.contents))] += value
        return self

    def __str__(self):
        if len(self._processed_titles) > 0:
            raise ValueError(
                "the following section titles are missing from the"
                " outline:\n\t"
                + "\n\t".join(self._processed_titles)
                + "\nEvery existing section must appear in the outline, so"
                " that entire sections of text are never dropped by"
                " accident.  If you really want to get rid of a section,"
                " add a new heading (e.g. 'for deletion') to the outline"
                " and move the unwanted sections underneath it; then delete"
                " that part of the file by hand."
            )
        retval = ""
        for j in self.contents.keys():
            if self.types[j] != "header":
                new_name = j
                if j in self._aliases.keys():
                    new_name = self._aliases[j]
                if self.format_type == "markdown":
                    retval += "#" * self.level_numbers[self.types[j]]
                    retval += f" {new_name}\n"
                else:
                    retval += f"\\{self.types[j]}{{{new_name}}}"
            retval += f"{self.contents[j]}"
        return retval

    @property
    def outline(self):
        retval = []
        for j in self.contents.keys():
            if self.types[j] != "header":
                indent = (self.level_numbers[self.types[j]] - 1) * "\t"
                thistitle = (indent + "\t").join(j.split("\n"))
                retval.append(indent + "*\t" + thistitle)
        return "\n".join(retval)

    def outline_in_order(self, outline_lines):
        self._processed_titles = [
            j for j in self.contents.keys() if self.types[j] != "header"
        ]
        # {{{ parse (level, title) from each outline line
        parsed = []
        for thisline in outline_lines:
            if not thisline.strip():
                continue
            ilevel = 0
            spacelevel = 0
            hitmarker = False
            for j, thischar in enumerate(thisline):
                if not hitmarker:
                    if thischar == " ":
                        spacelevel += 1
                    if spacelevel == 4 or thischar == "\t":
                        ilevel += 1
                        spacelevel = 0
                    elif thischar == "*":
                        hitmarker = True
                else:
                    assert thischar in [" ", "\t"]
                    title = thisline[j + 1 :]
                    break
            if not hitmarker:
                raise ValueError("somehow, there wasn't a * marker!")
            parsed.append((ilevel, title))
        # }}}
        # {{{ resolve titles that aren't existing sections -- only sections
        #     that appear nowhere in the outline can have been renamed
        outline_titles = {title for _, title in parsed}
        orphans = [
            j
            for j in self.contents.keys()
            if self.types[j] != "header" and j not in outline_titles
        ]
        renamed = {}
        for _, title in parsed:
            if title in self.contents.keys() or title in renamed:
                continue
            if re.search(r"\bNEW\b", title):
                print(f"adding\n\t{title}\nas a new section (labeled NEW)")
            elif len(orphans) == 0:
                print(
                    f"adding\n\t{title}\nas a new section (no unplaced"
                    " sections are left that it could be a rename of)"
                )
            else:
                ranked = sorted(
                    orphans,
                    key=lambda j: fuzz.token_sort_ratio(title, j),
                    reverse=True,
                )[:5]
                choices = "".join(
                    f"\n  {n + 1}) [{fuzz.token_sort_ratio(title, j)}] {j}"
                    for n, j in enumerate(ranked)
                )
                prompt = (
                    f"didn't find\n\t{title}\namong the existing sections."
                    " Is it a renamed version of one of these sections that"
                    f" don't appear in the outline?{choices}\nenter a number"
                    " to rename, n to add it as a new, empty section, or q"
                    " to quit without writing anything: "
                )
                while True:
                    answer = input(prompt).strip()
                    if answer in ("n", "q"):
                        break
                    if answer.isdigit() and 1 <= int(answer) <= len(ranked):
                        break
                    print(f"didn't understand {answer!r}")
                if answer == "q":
                    raise ValueError("aborted -- nothing was written")
                if answer != "n":
                    original = ranked[int(answer) - 1]
                    self._aliases[original] = title  # will be replaced later
                    renamed[title] = original
                    orphans.remove(original)
                    continue
            # a new section, so it isn't on the list of titles to place
            self.contents[title] = ""
            self._processed_titles.append(title)
        # }}}
        # {{{ reorder sections to match the outline
        for ilevel, title in parsed:
            title = renamed.get(title, title)
            if title not in self._processed_titles:
                raise ValueError(
                    f"the section\n\t{title}\nappears more than once in the"
                    " outline"
                )
            self.contents.move_to_end(title)
            self._processed_titles.remove(title)
            self.types[title] = self.inv_prefix[ilevel * "\t"]
        # }}}
