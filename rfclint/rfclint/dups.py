import io
import re
import os
import errno
import sys
import colorama
import six
import platform
import codecs
import subprocess
import curses
from rfctools_common import log


if six.PY2:
    import subprocess32
    subprocess = subprocess32
else:
    import subprocess

if os.name == 'nt':
    import msvcrt

    def get_character():
        return msvcrt.getch()
else:
    import tty
    import sys
    import termios

    def get_character():
        fd = sys.stdin.fileno()
        oldSettings = termios.tcgetattr(fd)

        try:
            tty.setcbreak(fd)
            answer = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, oldSettings)
            answer = None

        return answer


class RfcLintError(Exception):
    """ RFC Lint internal errors """
    def __init__(self, msg, filename=None, line_no=0):
        self.msg = msg
        self.message = msg
        self.position = line_no
        self.filename = filename
        self.line = line_no


def ReplaceWithSpace(exc):
    if isinstance(exc, UnicodeDecodeError):
        return u' '
    elif isinstance(exc, UnicodeEncodeError):
        if six.PY2:
            return ((exc.end - exc.start) * u' ', exc.end)
        else:
            return (bytes((exc.end - exc.start) * [32]), exc.end)
    else:
        raise TypeError("can't handle %s" % type(exc).__name__)


CheckAttributes = {
    "title": ['ascii', 'abbrev'],
    'seriesInfo': ['name', 'asciiName', 'value', 'asciiValue'],
    "author": ['asciiFullname', 'asciiInitials', 'asciiSurname', 'fullname', 'surname', 'initials'],
    'city': ['ascii'],
    'code': ['ascii'],
    'country': ['ascii'],
    'region': ['ascii'],
    'street': ['ascii'],
    'blockquote': ['quotedFrom'],
    'iref': ['item', 'subitem'],
}

CutNodes = {
    'annotation': 1,
    'area': 1,
    'artwork': 2,
    'blockquote': 2,
    'city': 1,
    'cref': 1,
    'code': 1,
    'country': 1,
    'dd': 2,
    'dt': 1,
    'email': 1,
    'keyword': 1,
    'li': 2,
    'name': 1,
    'organization': 1,
    'phone': 1,
    'postalLine': 1,
    'refcontent': 1,
    'region': 1,
    'sourcecode': 1,
    'street': 1,
    "t": 1,
    'td': 2,
    'th': 2,
    "title": 1,
    'uri': 1,
    'workgroup': 1,
}

# colorama.init()

SpellerColors = {
    'green': colorama.Fore.GREEN,
    'none': '',
    'red': colorama.Fore.RED,
    'bright': colorama.Style.BRIGHT
}
# BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE,

byte1 = b'\x31'
byte9 = b'\x39'


def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


class Dups(object):
    """ Object to deal with processing duplicates """
    def __init__(self, config):
        self.word_re = re.compile(r'(\W*\w+\W*)', re.UNICODE | re.MULTILINE)
        # self.word_re = re.compile(r'\w+', re.UNICODE | re.MULTILINE)
        self.aspell_re = re.compile(r".\s(\S+)\s(\d+)\s*((\d+): (.+))?", re.UNICODE)

        self.dupword_re = re.compile(r'\W*([\w\']+)\W*', re.UNICODE)

        self.interactive = False
        if True or config.options.output_filename is not None:
            self.interactive = True
            self.ignoreWords = []
            self.lastElement = None

        self.dup_re = re.compile(r'\w[\w\']*\w|\w', re.UNICODE)

    def processTree(self, tree):
        # log.warn("processTree - look at node {0}".format(tree.tag))
        if tree.tag in CheckAttributes:
            self.checkAttributes(tree)
        if tree.tag in CutNodes:
            self.checkTree(tree)
        for node in tree.iterchildren():
            self.processTree(node)

    def checkAttributes(self, tree):
        for attr in CheckAttributes[tree.tag]:
            if attr not in tree.attrib:
                continue
            words = [(tree.attrib[attr], tree, attr, 0)]
            results = self.processLine(words)
            self.processResults(words, results, attr)

    def checkTree(self, tree):
        wordSet = self.getWords(tree)
        results = self.processLine(wordSet)

        self.processResults(wordSet, results, None)

        # s = " ".join(words[max(0, i-10):min(len(words), i+10)])
        # s = s.replace(words[i], colorama.Fore.GREEN + ">>>" + words[i] + "<<<" +
        #       colorama.Style.RESET_ALL)
        # log.warn(s)
        # log.warn(results[i][results[i].rfind(':')+2:])

    def processLine(self, allWords):
        """
        """
        result = []
        setNo = 0
        for wordSet in allWords:
            for m in re.finditer(r'\w[\w\']*\w|\w', wordSet, re.UNICODE):
                tuple = (m.start, m.group(1), wordset[1], setNo)
                result.append(tuple)
            setNo += 1

        return result

    def getWords(self, tree):
        words = []
        if tree.text:
            line = -1
            for x in tree.text.splitlines():
                line += 1
                ll = x.strip()
                if ll:
                    words += [(ll, tree, True, line)]

        for node in tree.iterchildren():
            if node.tag in CutNodes:
                continue
            words += self.getWords(node)

            if node.tail:
                line = -1
                for x in tree.tail.splitlines():
                    line += 1
                    ll = x.strip()
                    if ll:
                        words += [(ll, tree, False, line)]

        return words

    def processResults(self, wordSet, results, attributeName):
        """  Process the results coming from a spell check operation """

        matchGroups = []
        allWords = []
        for words in wordSet:
            xx = self.word_re.finditer(words[0])
            for w in xx:
                if w:
                    matchGroups.append((w, words[1], words[2], words[3]))
                    allWords.append(w.group(1))
                    if allWords[-1][-1] not in [' ', '-', "'"]:
                        allWords[-1] += ' '

        for r in results:

            if self.interactive:
                self.Interact(r, matchGroups, allWords)
            else:
                if attributeName:
                    log.error("Misspelled word '{0}' in attribute '{1}'".format(r[3], attributeName),
                              where=r[2])
                else:
                    log.error(u"Misspelled word was found '{0}'".format(r[3]), where=r[2])
                if self.window > 0:
                    q = self.wordIndex(r[1], r[2], matchGroups)
                    if q >= 0:
                        ctx = ""
                        if q > 0:
                            ctx = "".join(allWords[max(0, q - self.window):q])
                        ctx += self.color_start + allWords[q] + self.color_end
                        if q < len(allWords):
                            ctx += "".join(allWords[q + 1:min(q + self.window + 1, len(allWords))])
                        log.error(ctx, additional=2)
                if self.suggest and r[4]:
                    suggest = " ".join(r[4].split()[0:10])
                    log.error(suggest, additional=2)

        # check for dups
        last = None
        for (m, el, inText, lineNo) in matchGroups:
            w1 = self.dupword_re.match(m.group(0))
            if w1 is None:
                pass
            g = w1.group(1)
            if last:
                if last == g:
                    if self.interactive:
                        offset = m.start(0) + w1.start(1)
                        self.interactiveDup(g, offset, el, matchGroups, allWords)
                    else:
                        log.error("Duplicate word found '{0}'".format(last), where=el)
            last = g

    def wordIndex(self, offset, el, matchArray):
        """
        Given an offset and element, find the index in the matchArray that matches
        """

        for i in range(len(matchArray)):
            m = matchArray[i]
            if m[1] == el and \
               (m[0].start(1) <= offset and offset < m[0].end(1)):
                return i
        return -1

    def Interact(self, r, matchGroups, allWords):
        #
        #  At the request of the RFC editors we use the ispell keyboard mappings
        #
        #  R - replace the misspelled word completely
        #  Space - Accept the word this time only.
        #  A - Accept word for this session.
        #  I - Accept the word, insert private dictionary as is
        #  U - Accept the word, insert private dictionary as lower-case
        #  0-n - Replace w/ one of the suggested words
        #  L - Look up words in the system dictionary - NOT IMPLEMENTED
        #  X - skip to end of the file
        #  Q - quit and don't save the file
        #  ? - Print help
        #

        self.window.erase()

        q = self.wordIndex(r[1], r[2], matchGroups)

        if allWords[q] in self.ignoreWords or allWords[q].lower() in self.ignoreWords:
            return

        ctx = ""
        if q > 0:
            ctx = "".join(allWords[0:q])
        ctx += self.color_start + allWords[q] + self.color_end
        ctx += "".join(allWords[q + 1:])

        fileName = r[2].base
        if fileName.startswith("file:///"):
            fileName = os.path.relpath(fileName[8:])
        elif fileName[0:6] == 'file:/':
            fileName = os.path.relpath(fileName[6:])
        elif fileName[0:7] == 'http://' or fileName[0:8] == 'https://':
            pass
        else:
            fileName = os.path.relpath(fileName)

        self.window.addstr(curses.LINES-15, 0, self.spaceline, curses.A_REVERSE)
        self.window.addstr(curses.LINES-14, 0, u"{1}:{2} Misspelled word was found '{0}'".format(r[3], fileName, r[2].sourceline))
        self.window.addstr(curses.LINES-13, 0, self.spaceline, curses.A_REVERSE)
        self.window.addstr(0, 0, ctx)

        # log.error("", additional=0)
        # log.error(ctx, additional=2)

        # log.error("", additional=0)
        suggest = r[4].split(' ')

        # list = ""
        # for i in range(min(10, len(suggest))):
        #     list += "{0}) {1} ".format(chr(i + 0x31), suggest[i])

        for i in range(min(10, len(suggest))):
            self.window.addstr(int(i/2) + curses.LINES-12, (i%2)*40, "{0}) {1}".format(chr(i+0x31), suggest[i]))

        self.window.addstr(curses.LINES-2, 0, self.spaceline, curses.A_REVERSE)
        self.window.addstr(curses.LINES-1, 0, "?")
        self.window.refresh()

        replaceWord = None

        while (True):
            # ch = get_character()
            ch = self.window.getch()
            if ch == ord(' '):
                return
            if ch == '?':
                self.PrintHelp()
            elif ch == ord('Q') or ch == ord('q'):
                self.window.addstr(curses.LINES-1, 0, "Are you sure you want to abort?")
                self.window.refresh()
                ch = self.window.getch()
                if ch == ord('Y') or ch == ord('y'):
                    sys.exit(1)
                self.window.addstr(curses.LINES-1, 0, "?" + ' '*30)
                self.window.refresh()
            elif ch == ord('I'):
                self.IgnoreWord(allWords[q])
                return
            elif ch == ord('U'):
                self.IgnoreWord(allWords[q].tolower())
                return
            elif ch == ord('X'):
                return
            elif ch == ord('R'):
                return
            elif 0x31 <= ch and ch <= 0x39:
                ch = ch - 0x31
                replaceWord = suggest[ch]
            elif ch == '0':
                replaceWord = suggest[9]
            else:
                pass

            if replaceWord is not None:
                r[2].text = self.replaceText(r[2].text, replaceWord, r)
                allWords[q] = replaceWord
                return
            log.write("\n> ")

    def replaceText(self, textIn, replaceWord, r):
        if replaceWord[-1] == ',':
            replaceWord = replaceWord[:-1]

        if self.lastElement != r[2]:
            self.offset = 0
            self.lastElement = r[2]
        textOut = textIn[:r[1]-2 + self.offset] + replaceWord + textIn[r[1]-2+self.offset+len(r[3]):]
        self.offset += len(replaceWord) - len(r[3])
        return textOut

    def interactiveDup(self, word, offset, element, matchGroups, allWords):
        self.window.erase()

        q = self.wordIndex(offset, element, matchGroups)

        self.window.move(0, 0)
        if q > 0:
            self.window.addstr("".join(allWords[0:q]))
        self.window.addstr(allWords[q], curses.A_REVERSE)
        self.window.addstr("".join(allWords[q + 1:]))

        fileName = element.base
        if fileName.startswith("file:///"):
            fileName = os.path.relpath(fileName[8:])
        elif fileName[0:6] == 'file:/':
            fileName = os.path.relpath(fileName[6:])
        elif fileName[0:7] == 'http://' or fileName[0:8] == 'https://':
            pass
        else:
            fileName = os.path.relpath(fileName)

        self.window.addstr(curses.LINES-15, 0, self.spaceline, curses.A_REVERSE)
        self.window.addstr(curses.LINES-14, 0, u"{1}:{2} Duplicate word found '{0}'".format(word, fileName, element.sourceline))
        self.window.addstr(curses.LINES-13, 0, self.spaceline, curses.A_REVERSE)

        self.window.addstr(curses.LINES-2, 0, self.spaceline, curses.A_REVERSE)
        self.window.addstr(curses.LINES-1, 0, "?")

        self.window.addstr(curses.LINES-11, 0, " ) Ignore")
        self.window.addstr(curses.LINES-10, 0, "D) Delete Word")
        self.window.addstr(curses.LINES-9, 0, "R) Replace Word")
        self.window.addstr(curses.LINES-8, 0, "Q) Quit")
        self.window.addstr(curses.LINES-7, 0, "X) Exit")

        self.window.addstr(curses.LINES-1, 0, "?")
        self.window.refresh()

        while (True):
            # ch = get_character()
            ch = self.window.getch()
            if ch == ord(' '):
                return
            if ch == '?':
                self.PrintHelp()
            elif ch == ord('Q') or ch == ord('q'):
                self.window.addstr(curses.LINES-1, 0, "Are you sure you want to abort?")
                self.window.refresh()
                ch = self.window.getch()
                if ch == ord('Y') or ch == ord('y'):
                    sys.exit(1)
                self.window.addstr(curses.LINES-1, 0, "?" + ' '*30)
                self.window.refresh()
            elif ch == ord('D'):
                element.text = self.removeText(element.text, word, offset, element)
                return
            elif ch == ord('X'):
                return
            elif ch == ord('R'):
                return
            else:
                pass

    def removeText(self, textIn, word, offset, el):
        if self.lastElement != el:
            self.offset = 0
            self.lastElement = el
        textOut = textIn[:offset + self.offset] + textIn[offset+self.offset+len(word):]
        self.offset +=  - len(word)
        return textOut

    def initscr(self):
        try:
            self.window = curses.initscr()
            curses.start_color()
            curses.noecho()
            curses.cbreak()
            self.spaceline = " "*curses.COLS

        except curses.error as e:
            self.window = None

    def endwin(self):
        if self.window:
            curses.nocbreak()
            curses.echo()
            curses.endwin()
