import re
from numpy import *
import sys
import logging
def match_curly_bracket(alltext,pos):
    if pos == 0:
        raise RuntimeError("can't deal with babel string at the very beginning of the file")
    if alltext[pos] == '{':
        parenlevel = 1
    else:
        raise ValueError("You aren't starting on a curly bracket")
    try:
        while parenlevel > 0:
            pos += 1
            if alltext[pos] == '{':
                if alltext[pos-1] != '\\':
                    parenlevel += 1
            elif alltext[pos] == '}':
                if alltext[pos-1] != '\\':
                    parenlevel -= 1
    except Exception as e:
        raise RuntimeError("hit end of file without closing a bracket, original error\n"+repr(e))
    return pos
def run(filename,
        wrapnumber = 45,
        punctuation_slop = 20,
        stupid_strip = False,
        ):
    if filename is not None:
        fp = open(filename)
        alltext = fp.read()
        fp.close()
    else:
        fp = sys.stdin
        alltext = fp.read()
    alltext = alltext.decode('utf-8')
    #{{{ strip stupid commands that appear in openoffice conversion
    if stupid_strip:
        alltext = re.sub(r'\\bigskip\b\s*','',alltext)
        alltext = re.sub(r'\\;','',alltext)
        alltext = re.sub(r'(?:\\ ){4}',r'\quad ',alltext)
        alltext = re.sub(r'\\ ',' ',alltext)
        #alltext = re.sub('\\\\\n',' ',alltext)
        #{{{ remove select language an accompanying bracket
        m = re.search(r'{\\selectlanguage{english}',alltext)
        while m:
            stop_bracket = match_curly_bracket(alltext,m.start())
            alltext = (alltext[:m.start()] + alltext[m.end():stop_bracket] +
                    alltext[stop_bracket+1:])# pos is the position of
            #                         the matching curly bracket
            m = re.search(r'{\\selectlanguage{english}',alltext)
        #}}}
        #{{{ remove the remaining select languages
        m = re.search(r'\\selectlanguage{english}',alltext)
        while m:
            alltext = alltext[:m.start()] + alltext[m.end():]
            m = re.search(r'\\selectlanguage{english}',alltext)
        #}}}
        #{{{ remove mathit
        m = re.search(r'\\mathit{',alltext)
        while m:
            logging.debug('-------------')
            logging.debug(alltext[m.start():m.end()])
            logging.debug('-------------')
            stop_bracket = match_curly_bracket(alltext,m.end()-1)
            alltext = (alltext[:m.start()] + alltext[m.end():stop_bracket] +
                    alltext[stop_bracket+1:])# pos is the position of
            #                         the matching curly bracket
            m = re.search(r'\\mathit{',alltext)
        #}}}
    #}}}
    alltext = alltext.split('\n\n') #split paragraphs
    for para in range(len(alltext)):# split paragraphs into sentences
        #{{{ here I need a trick to prevent including short abbreviations, etc
        tempsent = re.split('([^\.!?]{3}[\.!?])[ \n]',alltext[para])
        for j in tempsent:
            logging.debug("--",j.encode('utf-8'))
        #{{{ put the "separators together with the preceding
        temp_paragraph = []
        for tempsent_num in range(0,len(tempsent),2):
            if tempsent_num+1 < len(tempsent):
                temp_paragraph.append(tempsent[tempsent_num] + tempsent[tempsent_num+1])
            else:
                temp_paragraph.append(tempsent[tempsent_num])
        logging.debug('-------------------')
        alltext[para] = []
        for this_sent in temp_paragraph:
            alltext[para].extend(
                    re.split(r'(\\(?:begin|end|usepackage|newcommand){[^}]*})',this_sent))
        for this_sent in alltext[para]:
            logging.debug("--sentence: ",this_sent.encode('utf-8'))
        #}}}
        #}}}
        for sent in range(len(alltext[para])):# sentences into words
            alltext[para][sent] = [word for word in re.split('[ \n]+',alltext[para][sent]) if len(word) > 0]
    #{{{ now that it's organized into paragraphs, sentences, and
    #    words, wrap the sentences
    lines = []
    for para in range(len(alltext)):# paragraph number
        lines += ['\n'] # the extra line break between paragraphs
        for sent in range(len(alltext[para])):# sentences into words
            residual_sentence = alltext[para][sent]
            indentation = 0
            while len(residual_sentence) > 0:
                numchars = array(list(map(len,residual_sentence))) + 1 #+1 for space
                cumsum_num = cumsum(numchars)
                nextline_upto = argmin(abs(cumsum_num - wrapnumber))#
                #   the next line goes up to this position
                nextline_punct_upto = array([cumsum_num[j] if
                    (residual_sentence[j][-1] in
                        [',',';',':',')','-']) else 10000 for j
                    in range(len(residual_sentence)) ])
                if any(nextline_punct_upto < 10000):
                    nextline_punct_upto = argmin(abs(
                        nextline_punct_upto - wrapnumber))
                    if nextline_punct_upto < nextline_upto:
                        if nextline_upto - nextline_punct_upto < punctuation_slop:
                            nextline_upto = nextline_punct_upto
                lines.append(' '*indentation + ' '.join(residual_sentence[:nextline_upto+1]))
                residual_sentence = residual_sentence[nextline_upto+1:]
                if indentation == 0:
                    indentation = 4
    #}}}
    if filename is None:
        print(('\n'.join(lines)).encode('utf-8'))
    else:
        fp = open(filename,'w')
        fp.write(('\n'.join(lines)).encode('utf-8'))
        fp.close()
