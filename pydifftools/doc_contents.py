from collections import OrderedDict
from fuzzywuzzy import process


class doc_contents_class(object):
    def __init__(self, format_type="latex"):
        self.contents = OrderedDict()
        self.contents["header"] = ""
        self.types = {}
        self.types["header"] = "header"
        self._reordering_started = False
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
        self._reordering_started = False
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
                "the following section"
                " titles were not utilized -- this program is"
                " for reordering, not dropping!:\n"
                + str(self._processed_titles)
            )
        retval = ""
        for j in self.contents.keys():
            if self.types[j] != "header":
                new_name = j
                if j in self._aliases.keys():
                    new_name = self._aliases[j]
                if self.format_type == "markdown":
                    retval += "#" * self.level_numbers[self.types[j]]
                    retval += f" {new_name}\n\n"
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
        self._reordering_started = False
        return "\n".join(retval)

    def outline_in_order(self, thisline):
        if not self._reordering_started:
            self._processed_titles = [
                j for j in self.contents.keys() if self.types[j] != "header"
            ]
            self._reordering_started = True
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
        if title not in self.contents.keys():
            best_match, match_quality = process.extractOne(
                title, self.contents.keys()
            )
            yesorno = input(
                f"didn't find\n\t{title}\nin keys, maybe you"
                f" want\n\t{best_match}\nsay y or n"
            )
            if yesorno == "y":
                self._aliases[best_match] = title  # will be replaced later
                title = best_match
            else:
                raise ValueError("problem with replacement")
        self.contents.move_to_end(title)
        self._processed_titles.remove(title)
        self.types[title] = self.inv_prefix[ilevel * "\t"]
