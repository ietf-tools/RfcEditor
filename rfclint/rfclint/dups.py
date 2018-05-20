import io
import re
import os
import errno
import sys
import colorama
import six
import platform
import codecs
try:
    import curses
    haveCurses = True
except ImportError:
    haveCurses = False

from rfctools_common import log
from rfclint.spell import RfcLintError, CheckAttributes, CutNodes


class Dups(object):
    """ Object to deal with processing duplicates """
    def __init__(self, config):
        self.word_re = re.compile(r'(\W*\w+\W*)', re.UNICODE | re.MULTILINE)
        # self.word_re = re.compile(r'\w+', re.UNICODE | re.MULTILINE)
        self.aspell_re = re.compile(r".\s(\S+)\s(\d+)\s*((\d+): (.+))?", re.UNICODE)

        self.dupword_re = re.compile(r'\W*([\w\']+)\W*', re.UNICODE)

        self.interactive = False
        self.no_curses = False
        self.curses = None
        if config.options.output_filename is not None:
            self.interactive = True
            self.lastElement = None
            self.textLocation = True

        self.dup_re = re.compile(r' *\w[\w\']*\w|\w', re.UNICODE)

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

    def processLine(self, allWords):
        """
        """
        result = []
        setNo = 0
        for wordSet in allWords:
            for m in re.finditer(r'\w[\w\']*\w|\w', wordSet[0], re.UNICODE):
                tuple = (m.start(), m.group(0), wordSet[1], setNo)
                result.append(tuple)
            setNo += 1

        return result

    def getWords(self, tree):
        words = []
        if tree.text:
            words += [(tree.text, tree, True, -1)]

        for node in tree.iterchildren():
            if node.tag in CutNodes:
                continue
            words += self.getWords(node)

            if node.tail:
                words += [(node.tail, node, False, -1)]

        return words

    def processResults(self, wordSet, results, attributeName):
        """  Process the results coming from a spell check operation """

        matchGroups = []
        allWords = []
        for words in wordSet:
            xx = self.word_re.finditer(words[0])
            for w in xx:
                if w:
                    matchGroups.append((w, words[1]))
                    allWords.append(w.group(1))
                    if allWords[-1][-1] not in [' ', '-', "'"]:
                        allWords[-1] += ' '

        # check for dups
        last = None
        for words in wordSet:
            xx = self.dup_re.finditer(words[0])
            for w in xx:
                g = w.group(0).strip().lower()
                if last:
                    # print("compare '{0}' and '{1}'".format(last, g))
                    if last == g:
                        if self.interactive:
                            self.Interact(words[1], w, -1, allWords, wordSet, words)
                        else:
                            if attributeName:
                                log.error("Duplicate word found '{0}' in attribute '{1}'".
                                          format(last, attributeName), where=words[1])
                            else:
                                log.error("Duplicate word found '{0}'".format(last),
                                          where=words[1])

                last = g

    def Interact(self, element, match, srcLine, allWords, wordSet, words):
        if self.curses:
            self.curses.erase()

            self.curses.move(0, 0)

        fileName = element.base
        if fileName.startswith("file:///"):
            fileName = os.path.relpath(fileName[8:])
        elif fileName[0:6] == 'file:/':
            fileName = os.path.relpath(fileName[6:])
        elif fileName[0:7] == 'http://' or fileName[0:8] == 'https://':
            pass
        else:
            fileName = os.path.relpath(fileName)

        y = 0
        self.x = 0
        self.y = 0

        if self.curses:
            if isinstance(words[2], str):
                self.curses.addstr(curses.LINES-14, 0,
                                   u"{1}:{2} Duplicate word '{0}' found in attribute '{3}'".
                                   format(match.group(0), fileName, element.sourceline, words[2]))
            else:
                self.curses.addstr(curses.LINES-14, 0, u"{1}:{2} Duplicate word found '{0}'".
                                   format(match.group(0), fileName, element.sourceline))
        else:
            log.write("")
            if isinstance(words[2], str):
                log.error(u"{1}:{2} Duplicate word '{0}' found in attribute '{3}'".
                          format(match.group(0), fileName, element.sourceline, words[2]))
            else:
                log.error(u"{1}:{2} Duplicate word found '{0}'".
                          format(match.group(0), fileName, element.sourceline))

        for line in wordSet:
            if isinstance(line[2], str):
                text = line[1].attrib[line[2]]
            elif line[2]:
                text = line[1].text
            else:
                text = line[1].tail
            if words == line:
                if self.lastElement != line[1] or self.textLocation != line[2]:
                    self.offset = 0
                    self.lastElement = line[1]
                    self.textLocation = line[2]
                self.writeString(text[:match.start()+self.offset], partialString=True)
                self.writeString(text[match.start()+self.offset:match.end()+self.offset],
                                 self.A_REVERSE, True)
                self.writeString(text[match.end()+self.offset:])
            else:
                self.writeString(text)
            y += 1

        if self.curses:
            self.curses.addstr(curses.LINES-15, 0, self.spaceline, self.A_REVERSE)
            self.curses.addstr(curses.LINES-13, 0, self.spaceline, self.A_REVERSE)

            self.curses.addstr(curses.LINES-2, 0, self.spaceline, self.A_REVERSE)
            self.curses.addstr(curses.LINES-1, 0, "?")

            self.curses.addstr(curses.LINES-11, 0, " ) Ignore")
            self.curses.addstr(curses.LINES-10, 0, "D) Delete Word")
            self.curses.addstr(curses.LINES-9, 0, "R) Replace Word")
            self.curses.addstr(curses.LINES-8, 0, "Q) Quit")
            self.curses.addstr(curses.LINES-7, 0, "X) Exit")

            self.curses.addstr(curses.LINES-1, 0, "?")
            self.curses.refresh()
        else:
            log.write("")

        while (True):
            # ch = get_character()
            if self.curses:
                ch = chr(self.curses.getch())
            else:
                ch = input("? ")
                ch = (ch + "b")[0]

            if ch == ' ':
                return
            if ch == '?':
                if not self.curses:
                    log.error("HELP:  ) Ignore, D) Delete Word, R) Replace Word, Q) Quit, X) Exit.",
                              additional=0)
            elif ch == 'Q' or ch == 'q':
                if self.curses:
                    self.curses.addstr(curses.LINES-1, 0, "Are you sure you want to abort?")
                    self.curses.refresh()
                    ch = self.curses.getch()
                else:
                    ch = input("Are you sure you want to abort? ")
                    ch = (ch + 'x')[0]
                if ch == 'Y' or ch == 'y':
                    sys.exit(1)

                if self.curses:
                    self.curses.addstr(curses.LINES-1, 0, "?" + ' '*30)
                    self.curses.refresh()
            elif ch == 'D' or ch == 'd':
                if isinstance(line[2], str):
                    element.attrib[line[2]] = self.removeText(element.attrib[line[2]], match,
                                                              element)
                elif words[2]:
                    element.text = self.removeText(element.text, match, element)
                else:
                    element.tail = self.removeText(element.tail, match, element)
                return
            elif ch == 'X':
                return
            elif ch == 'R':
                if self.curses:
                    self.curses.addstr(curses.LINES-1, 0, "Replace with: ")
                    self.curses.refresh()
                    ch = ''
                    while True:
                        ch2 = chr(self.curses.getch())
                        if ch2 == '\n':
                            break
                        ch += ch2
                else:
                    ch = input("Replace with: ")

                if isinstance(line[2], str):
                    element.attrib[line[2]] = self.replaceText(element.attrib[line[2]], ch, match,
                                                               element)
                elif words[2]:
                    element.text = self.replaceText(element.text, ch, match, element)
                else:
                    element.tail = self.replaceText(element.tail, ch, match, element)
                return
            else:
                pass

    def removeText(self, textIn, match, el):
        textOut = textIn[:match.start() + self.offset] + textIn[match.end()+self.offset:]
        self.offset += -(match.end() - match.start())
        return textOut

    def replaceText(self, textIn, replaceWord, match, el):
        startChar = match.start() + self.offset
        while textIn[startChar] == ' ':
            startChar += 1

        textOut = textIn[:startChar] + replaceWord + \
            textIn[match.end()+self.offset:]
        self.offset += len(replaceWord) - (match.end() - match.start())
        return textOut

    def writeString(self, text, color=0, partialString=False):
        newLine = False
        cols = 80
        if self.curses:
            cols = curses.COLS
            if color == 0:
                color = curses.A_NORMAL
        for line in text.splitlines(1):
            if line[:-1] == '\n':
                newLine = True
                line = line[:-1]
            while self.x + len(line) >= cols:
                if self.curses:
                    self.curses.addstr(self.y, self.x, line[:cols-self.x - 2], color)
                    self.curses.addstr("/", color)
                else:
                    log.write_on_line(line[:cols-self.x - 2])
                    log.write_on_line("/")
                line = line[cols-self.x-2:]
                self.x = 0
                self.y += 1
                if not self.curses:
                    log.write("")
            if self.curses:
                self.curses.addstr(self.y, self.x, line, color)
            else:
                log.write_on_line(line)
            self.x += len(line)
            if newLine:
                if self.x != 0:
                    self.x = 0
                    self.y += 1
                    if not self.curses:
                        log.write("")
                newLine = False
            if self.x != 0 and line[-1] != ' ' and not partialString:
                self.x += 1

    def initscr(self):
        try:
            self.A_REVERSE = 0
            self.A_NORMAL = 0
            if haveCurses and not self.no_curses:
                self.curses = curses.initscr()
                curses.start_color()
                curses.noecho()
                curses.cbreak()
                self.spaceline = " "*curses.COLS
                self.A_REVERSE = curses.A_REVERSE
                self.A_NORMAL = curses.A_NORMAL

        except curses.error as e:
            self.curses = None

    def endwin(self):
        if self.curses:
            curses.nocbreak()
            curses.echo()
            curses.endwin()
