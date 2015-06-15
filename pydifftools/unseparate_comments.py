import re
import sys
from comment_functions import generate_alphabetnumber,matchingbrackets
if sys.argv[1][-12:] == '_sepcomm.tex':
    base_filename = sys.argv[1][:-12]
    print "yes, a _sepcomm.tex file called",base_filename,'.tex'
elif sys.argv[1][-4:] == '.tex':
    base_filename = sys.argv[1][:-4]
    print "yes, a .tex file called",base_filename,'.tex'
else:
    raise RuntimeError("not a tex file??")
fp = open(base_filename+'_comments.tex','r')
content = fp.read()
fp.close()
#comment_def_re = re.compile(r"\\newcommand\{\%s[A-Z]+")
names = ["john", "peter", "ntd", "songi", "yuan"]
list_of_names = []
list_of_commands = []
list_of_content = []
for j in range(0,len(names)):
    comment_def_re = re.compile(r"\\newcommand\{\\(%s[A-Z]+)\}\[1\]\{\\%smark\{#1\}\\%sbubble\{"%((names[j],)*3))
    for m in comment_def_re.finditer(content):
        print "found %d:%d"%(m.start(),m.end()),m.groups()[0]
        print "text:",content[m.start():m.end()]
        a,b = matchingbrackets(content,m.end()-1,'{')
        print "found from %d to %d"%(a,b)
        print "-----content------"
        print content[a:b+1]
        print "------------------"
        list_of_names.append(names[j])
        list_of_commands.append(m.groups()[0])
        list_of_content.append(content[a+1:b])
fp = open(sys.argv[1],'r')
content = fp.read()
fp.close()
for j in range(0,len(list_of_names)):
    a = content.find("\\%s"%list_of_commands[j])
    if a<0:
        raise RuntimeError("couldn't find command \\%s"%list_of_commands[j])
    else:
        starthighlight,b = matchingbrackets(content,a,'{')
        highlight = content[starthighlight+1:b]
        print "found command \\%s with highlight {%s} and going to add content {%s}"%(list_of_commands[j],highlight,list_of_content[j])
        if len(highlight) > 0:
            content = content[:a] + '\\%s[%s]{%s}'%(list_of_names[j],highlight,list_of_content[j]) + content[b+1:]
        else:
            content = content[:a] + '\\%s{%s}'%(list_of_names[j],list_of_content[j]) + content[b+1:]
content = re.sub('\\\\include{%s_comments}\n'%base_filename,'',content)
content = re.sub('%%NUMBER OF COMMENTS [0-9]+ *\n','',content)
fp = open(base_filename+'_unsep.tex','w')
fp.write(content)
fp.close()
