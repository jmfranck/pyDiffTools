import re
from numpy import *
def run(arguments,
        wrapnumber = 45,
        punctuation_slop = 20,
        ):
    fp = open(arguments[0])
    alltext = fp.read()
    fp.close()
    alltext = alltext.decode('utf-8')
    alltext = alltext.split('\n\n') #split paragraphs
    for para in range(len(alltext)):# split paragraphs into sentences
        #{{{ here I need a trick to prevent including short abbreviations, etc
        tempsent = re.split('([^\.!?]{3}[\.!?])[ \n]',alltext[para])
        for j in tempsent:
            print "--",j.encode('utf-8')
        #{{{ put the "separators together with the preceding
        alltext[para] = []
        for tempsent_num in range(0,len(tempsent),2):
            if tempsent_num+1 < len(tempsent):
                alltext[para].append(tempsent[tempsent_num] + tempsent[tempsent_num+1])
            else:
                alltext[para].append(tempsent[tempsent_num])
        print '-------------------'
        for j in alltext[para]:
            print "--",j.encode('utf-8')
        #}}}
        #}}}
        for sent in range(len(alltext[para])):# sentences into words
            alltext[para][sent] = [word for word in re.split('[ \n]+',alltext[para][sent]) if len(word) > 0]
        ##{{{ join any sentences that end in know abbrevs
        #sent = 0
        #while sent < len(alltext[para]):
        #    if len(alltext[para][sent]) > 0:
        #        if alltext[para][sent][-1] in abbreviations and sent < len(alltext[para]):
        #            alltext[para][sent:sent+1] = [alltext[para][sent] + alltext[para][sent+1]]
        #    sent += 1
        ##}}}
    lines = []
    for para in range(len(alltext)):# split paragraphs into sentences
        lines += ['\n'] # the extra line break between paragraphs
        for sent in range(len(alltext[para])):# sentences into words
            residual_sentence = alltext[para][sent]
            indentation = 0
            while len(residual_sentence) > 0:
                numchars = array(map(len,residual_sentence)) + 1 #+1 for space
                cumsum_num = cumsum(numchars)
                nextline_upto = argmin(abs(cumsum_num - wrapnumber))
                nextline_punct_upto = array([cumsum_num[j] if (residual_sentence[j][-1] in [u',',u';',u':',u')',u'-']) else 10000 for j in range(len(residual_sentence)) ])
                if any(nextline_punct_upto < 10000):
                    nextline_punct_upto = argmin(abs(nextline_punct_upto - wrapnumber))
                    if nextline_punct_upto < nextline_upto:
                        if nextline_upto - nextline_punct_upto < punctuation_slop:
                            nextline_upto = nextline_punct_upto
                lines.append(' '*indentation + ' '.join(residual_sentence[:nextline_upto+1]))
                residual_sentence = residual_sentence[nextline_upto+1:]
                if indentation == 0:
                    indentation = 4
    fp = open(arguments[0],'w')
    fp.write(('\n'.join(lines)).encode('utf-8'))
    fp.close()
