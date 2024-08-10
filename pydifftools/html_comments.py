# again rerun
from lxml import html, etree
import os
from pyspecdata.fornotebook import *
from pyspecdata import *
import re

fp = open(sys.argv[1], "r")
content = fp.read()
fp.close()
doc = html.fromstring(content)
commentlabel_re = re.compile(r"\[([A-Z]+)([0-9])\]")
comment_dict = {}
# for j in doc.xpath('descendant::*[@style="mso-element:comment"]'):
newlist = []
thisbody = doc.find("body")
print("I found the body", lsafen(thisbody))
commentlist = etree.Element("div", style="mso-element:comment-list")
for j in doc.xpath('//span[@style="mso-element:comment"]'):
    # for j in doc.xpath('//span[@style="mso-element:comment"]'):
    # print 'found span with style:\n\n',lsafen(html.tostring(j),wrap = 60)
    # if j.attrib['style'] == 'mso-element:comment':
    print("found span with style:\n\n", lsafen(j.attrib, wrap=60))
    newlist.append(j)
    j.drop_tree()
    commentlist.append(j)
thisbody.append(commentlist)
# print lsafen(map(html.tostring,newlist),wrap = 60)
newfile = re.sub(r"(.*)(\.htm.*)", r"\1_htmlcomm\2", sys.argv[1])
fp = open(newfile, "w")
content = html.tostring(doc)
fp.write(content)
fp.close()
