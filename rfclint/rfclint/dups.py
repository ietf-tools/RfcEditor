import io
import re
import os
import errno
import sys
import colorama
import six
import platform
import codecs
import curses
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
        self.window = None
        if config.options.output_filename is not None:
            self.interactive = True
            self.ignoreWords = []
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

    def Interact(self, element, match, srcLine, allWords, wordSet, words):
        if self.window:
            self.window.erase()

            self.window.move(0, 0)

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

        if self.window:
            if isinstance(words[2], str):
                self.window.addstr(curses.LINES-14, 0,
                                   u"{1}:{2} Duplicate word '{0}' found in attribute '{3}'".
                                   format(match.group(0), fileName, element.sourceline, words[2]))
            else:
                self.window.addstr(curses.LINES-14, 0, u"{1}:{2} Duplicate word found '{0}'".
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
                                 curses.A_REVERSE, True)
                self.writeString(text[match.end()+self.offset:])
            else:
                self.writeString(text)
            y += 1

        if self.window:
            self.window.addstr(curses.LINES-15, 0, self.spaceline, curses.A_REVERSE)
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
        else:
            log.write("")

        while (True):
            # ch = get_character()
            if self.window:
                ch = chr(self.window.getch())
            else:
                ch = input("? ")[0]

            if ch == ' ':
                return
            if ch == '?':
                if not self.window:
                    log.error("HELP:  ) Ignore, D) Delete Word, R) Replace Word, Q) Quit, X) Exit.",
                              additional=0)
            elif ch == 'Q' or ch == 'q':
                if self.window:
                    self.window.addstr(curses.LINES-1, 0, "Are you sure you want to abort?")
                    self.window.refresh()
                    ch = self.window.getch()
                else:
                    ch = input("Are you sure you want to abort? ")[0]
                if ch == 'Y' or ch == 'y':
                    sys.exit(1)

                if self.window:
                    self.window.addstr(curses.LINES-1, 0, "?" + ' '*30)
                    self.window.refresh()
            elif ch == 'D' or ch == 'd':
                if isinstance(line[2], str):
                    element.attrib[line[2]] = self.removeText(element.attrib[line[2]], match,
                                                              srcLine, element)
                elif words[2]:
                    element.text = self.removeText(element.text, match, srcLine, element)
                else:
                    element.tail = self.removeText(element.tail, match, srcLine, element)
                return
            elif ch == 'X':
                return
            elif ch == 'R':
                if self.window:
                    self.window.addstr(curses.LINES-1, 0, "Replace with: ")
                    self.window.refresh()
                    ch = ''
                    while True:
                        ch2 = chr(self.window.getch())
                        if ch2 == '\n':
                            break
                        ch += ch2
                else:
                    ch = input("Replace with: ")

                if isinstance(line[2], str):
                    element.attrib[line[2]] = self.replaceText(element.attrib[line[2]], ch, match,
                                                               srcLine, element)
                elif words[2]:
                    element.text = self.replaceText(element.text, ch, match, srcLine, element)
                else:
                    element.tail = self.replaceText(element.tail, ch, match, srcLine, element)
                return
            else:
                pass

    def removeText(self, textIn, match, srcLine, el):
        textOut = textIn[:match.start() + self.offset] + textIn[match.end()+self.offset:]
        self.offset += -(match.end() - match.start())
        return textOut

    def replaceText(self, textIn, replaceWord, match, srcLine, el):
        startChar = match.start() + self.offset
        while textIn[startChar] == ' ':
            startChar += 1

        textOut = textIn[:startChar] + replaceWord + \
            textIn[match.end()+self.offset:]
        self.offset += len(replaceWord) - (match.end() - match.start())
        return textOut

    def writeString(self, text, color=curses.A_NORMAL, partialString=False):
        newLine = False
        cols = 80
        if self.window:
            cols = curses.COLS
        for line in text.splitlines(1):
            if line[:-1] == '\n':
                newLine = True
                line = line[:-1]
            while self.x + len(line) >= cols:
                if self.window:
                    self.window.addstr(self.y, self.x, line[:cols-self.x - 2], color)
                    self.window.addstr("/", color)
                else:
                    log.write_on_line(line[:cols-self.x - 2])
                    log.write_on_line("/")
                line = line[cols-self.x-2:]
                self.x = 0
                self.y += 1
                if not self.window:
                    log.write("")
            if self.window:
                self.window.addstr(self.y, self.x, line, color)
            else:
                log.write_on_line(line)
            self.x += len(line)
            if newLine:
                if self.x != 0:
                    self.x = 0
                    self.y += 1
                    if not self.window:
                        log.write("")
                newLine = False
            if self.x != 0 and line[-1] != ' ' and not partialString:
                self.x += 1

    def initscr(self):
        try:
            if not self.no_curses:
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
