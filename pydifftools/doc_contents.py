from collections import OrderedDict
from fuzzywuzzy import process


class doc_contents_class(object):
    prefix = {
        "section": "",
        "subsection": "\t",
        "subsubsection": 2 * "\t",
        "paragraph": 3 * "\t",
    }
    inv_prefix = {v: k for k, v in prefix.items()}

    def __init__(self):
        self.contents = OrderedDict()
        self.contents["header"] = ""
        self.types = {}
        self.types["header"] = "header"
        self._reordering_started = False
        self._aliases = {}

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
        self._aliases = {} # doesn't exist, but still needed
        self._reordering_started = False
        return

    def __getstate__(self):
        "return info for a pickle"
        return {
            "contents": self.contents,
            "types": self.types,
        }

    def __iadd__(self, value):
        self.contents[next(reversed(self.contents))] += value
        return self

    def __str__(self):
        if len(self._processed_titles) > 0:
            raise ValueError("the following section"
            " titles were not utilized -- this program is"
            " for reordering, not dropping!:\n"+str(self._processed_titles))
        retval = ""
        for j in self.contents.keys():
            if self.types[j] != "header":
                new_name = j
                if j in self._aliases.keys():
                    new_name = self._aliases[j]
                retval += f"\\{self.types[j]}{{{new_name}}}"
            retval += f"{self.contents[j]}"
        return retval

    @property
    def outline(self):
        retval = []
        for j in self.contents.keys():
            if self.types[j] != "header":
                thistitle = (self.prefix[self.types[j]] + "\t").join(j.split("\n"))
                retval.append(self.prefix[self.types[j]] + "*\t" + thistitle)
        self._reordering_started = False
        return "\n".join(retval)

    def outline_in_order(self, thisline):
        if not self._reordering_started:
            self._processed_titles = [j for j in self.contents.keys()
                    if self.types[j] != 'header']
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
            best_match, match_quality = process.extractOne(title, self.contents.keys())
            yesorno = input(f"didn't find\n\t{title}\nin keys, maybe you want\n\t{best_match}\nsay y or n")
            if yesorno == 'y':
                self._aliases[best_match] = title # will be replaced later
                title = best_match
            else:
                raise ValueError("problem with replacement")
        self.contents.move_to_end(title)
        self._processed_titles.remove(title)
        self.types[title] = self.inv_prefix[ilevel * "\t"]
