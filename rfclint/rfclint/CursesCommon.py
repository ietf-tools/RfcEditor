try:
    import curses
    haveCurses = True
except ImportError:
    haveCurses = False


class CursesCommon(object):
    def __init__(self, config):
        self.no_curses = False
        self.curses = None
        
        self.interactive = False

        if config.options.output_filename is not None:
            self.interactive = True

    def initscr(self):
        try:
            self.A_REVERSE = 0
            self.A_NORMAL = 0
            if self.interactive and not self.no_curses:
                if haveCurses:
                    self.curses = curses.initscr()
                    curses.start_color()
                    curses.noecho()
                    curses.cbreak()
                    self.spaceline = " "*curses.COLS
                    self.A_REVERSE = curses.A_REVERSE
                    self.A_NORMAL = curses.A_NORMAL
                else:
                    log.warn("Unable to load CURSES for python")

        except curses.error as e:
            self.curses = None

    def endwin(self):
        if self.curses:
            curses.nocbreak()
            curses.echo()
            curses.endwin()
            
    def writeStringInit(self):
        self.lines = []
        self.hilight = []

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
                self.lines.append(line[:cols - self.x - 2] + "\\")
                line = line[cols-self.x-2:]
                self.x = 0
                self.y += 1
            if self.x == 0:
                self.lines.append(line)
            else:
                self.lines[-1] += line
            self.x += len(line)
            if newLine:
                if self.x != 0:
                    self.x = 0
                    self.y += 1
                newLine = False
            if self.x != 0 and line[-1] != ' ' and not partialString:
                self.lines[-1] += " "

    def writeStringEnd(self):
        if self.curses:
            self.curses.addstr(self.y, self.x, line, color)
        else:
            log.write_on_line(line)
