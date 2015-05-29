import re
import sys
from comment_functions import generate_alphabetnumber,matchingbrackets,comment_definition
if sys.argv[1][-4:] == '.tex':
    base_filename = sys.argv[1][:-4]
    print "yes, a tex file called",base_filename,'.tex'
else:
    raise RuntimeError("not a tex file??")
fp = open(base_filename+'.tex','r')
content = fp.read()
fp.close()
comment_string = '%%NUMBER OF COMMENTS'
a = content.find(comment_string)
if a>0:
    b = content.find('\n',a+len(comment_string))
    num_matches = int(content[a+len(comment_string):b])
    print "found %d comments already!"%num_matches
else:
    num_matches = 0
content = content.replace(r'\begin{document}',"\\include{%s_comments}\n\\begin{document}"%base_filename)
comment_collection = ''
names = ["john", "peter", "ntd", "songi", "yuan"]
name_list = '('+'|'.join(names)+')'
comment_re = re.compile(r"\\%s([\[\{])"%(name_list))
thismatch = comment_re.search(content) #match doesn't work with newlines, apparently
while thismatch:
    before = content[:thismatch.start()]
    thisname,bracket_type = thismatch.groups()
    a,b = matchingbrackets(content,thismatch.start(),bracket_type)
    if bracket_type == '[':
        highlight = content[a+1:b]
        a,b = matchingbrackets(content,b,'{')
        print "found comment:",content[a:b+1]
        comment = content[a+1:b]
        endpoint = b
    else:
        highlight = ''
        comment = content[a+1:b]
        endpoint = b
    after = content[endpoint+1:]
    # replace and search again
    envstring = thisname+generate_alphabetnumber(num_matches)
    print '%s--------------------'%envstring
    print "highlight:\n",highlight
    print "comment:\n",comment
    print '--------------------'
    print "before replace:\n",content[thismatch.start():endpoint]
    content = before + r"\%s"%envstring + "{" + highlight + "}" + after 
    print '--------------------'
    print "after replace:\n",content[thismatch.start():endpoint]
    print '--------------------'
    comment_collection += comment_definition(envstring,thisname,comment)
    thismatch = comment_re.search(content)
    num_matches += 1
fp = open(base_filename+'_sepcomm.tex','w')
comment_string = '%%%%NUMBER OF COMMENTS %d\n'%num_matches
content = content.replace(r'\begin{document}',comment_string+"\\begin{document}")
fp.write(content)
fp.close()
fp = open(base_filename+'_comments.tex','w')
fp.write(comment_collection)
fp.close()
