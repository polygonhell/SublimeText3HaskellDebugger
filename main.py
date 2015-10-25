import sublime, sublime_plugin
import re, subprocess

# This is messy but makes integration much easier
import os, sys, inspect

if os.name == 'posix':
    POSIX = True
    import fcntl
    import select
else:
    POSIX = False

_debugging = False
_debuggerRegion = "__Debugger Region__"

print("Posix = ", POSIX)


class Process(object):
    popen = None

    def __init__(self):
        self.popen = subprocess.Popen(
            ["/usr/local/bin/ghc", "--interactive"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
            )

        if POSIX:
            flags = fcntl.fcntl(self.popen.stdout, fcntl.F_GETFL)
            fcntl.fcntl(self.popen.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)


    def read_bytes(self):
        out = self.popen.stdout
        if POSIX:
            # while True:
            i, _, _ = select.select([out], [], [], 0.1)
            if i:
                return out.read(4096)
            else:
                return b""
        else:
            # this is windows specific problem, that you cannot tell if there
            # are more bytes ready, so we read only 1 at a times

            # while True:
                byte = self.popen.stdout.read(1)
                return [byte]

    last_line = ""
    cur_line = ""
    # this is less than ideal really you want a protocol with some form of ready in it
    def read_line(self):
        if (not ("\n" in self.cur_line)):
            while True:
                newChars = self.read_bytes().decode("UTF-8")
                self.cur_line += newChars
                if ("\n" in self.cur_line or len(newChars) == 0):
                    break
        if ("\n" in self.cur_line):
            self.last_line, sep, self.cur_line = self.cur_line.partition("\n")
            return self.last_line
        else:
            return None


    def write_bytes(self, bytes):
        si = self.popen.stdin
        si.write(bytes)
        si.flush()


    def kill(self):
        self._killed = True
        self.write_bytes(":q\n".encode("UTF-8"))
        self.popen.kill()


class ReplaceContentsCommand(sublime_plugin.TextCommand):
    def run(self, edit, path):
        print("Replacing contents with " + path)
        f = open(path, 'r', encoding='utf8')
        self.view.set_read_only(False)
        self.view.insert(edit, 0, f.read())
        self.view.set_read_only(True)


class Debugger(object):
    viewId = None
    paths = None
    file = None
    process = None

    def __init__(self):
        None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        print("Exiting - killing process")
        if self.process:
            self.process.kill()
            self.process = None

    def __del__(self):
        print("Exiting - killing process")
        if self.process:
            self.process.kill()
            self.process = None

    def highlight_selection(self, view, l1, p1, l2, p2):
        endPt = view.line(view.text_point(int(l2)-1, 0)).b
        pt1 = view.text_point(int(l1)-1, int(p1)-1)
        pt2 = min(view.text_point(int(l2)-1, int(p2)), endPt)
        region = sublime.Region(pt1, pt2)
        view.add_regions(_debuggerRegion, [region], "comment", "bookmark", sublime.DRAW_NO_FILL)
        view.show(region)

    def open(self, originalView):
        window = originalView.window()
        found = None
        for v in window.views():
            if (v.id() == self.viewId):
                found = v
                break
        view = found or window.new_file()
        self.viewId = view.id()
        view.set_scratch(True)
        view.set_name("*Debugger*")     
        view.set_syntax_file("Packages/SublimeHaskell/Syntaxes/Haskell-SublimeHaskell.tmLanguage")
        view.set_read_only(True)

        window.focus_view(view)

        # restart the debugger process
        if self.process:
            self.process.kill()
        self.process = Process()
        response = self.read_response()

        # CD to the buffers directory
        path, name = os.path.split(originalView.file_name())

        response = self.send_command(":cd " + path)
        response = self.send_command(":show paths")
        self.paths = self.parse_paths(response)
        print("paths: ", self.paths)

        # Load the file
        response = self.send_command(":load " + name)
        print("response: ", response)

        # set a breakpoint and enter main
        response = self.send_command(":break main")
        print("response: ", response)
        response = self.send_command(":main")
        print("response: ", response)

        # Find the file
        fileName, l1, p1, l2, p2 = self.parse_output(self.process.cur_line)
        self.file = fileName
        path = os.path.join(self.paths[0], fileName)
        view.run_command("replace_contents", {"path": path})
        self.highlight_selection(view, l1, p1, l2, p2)

        global _debugging
        _debugging = True


    def parse_paths(self, response):
        regex = "/.*"
        paths = []
        for r in response[1:]:
            path = re.findall(regex, r)
            if not path:
                break
            print(path)
            paths += path
        return paths

    def send_command(self, cmd):
        self.process.write_bytes((cmd + "\n").encode("UTF-8"))
        return self.read_response()

    def read_response_part(self):
        lines = []
        while True:
            str = self.process.read_line()
            if str != None:
                lines.append(str)
            else:
                break
        return lines

    def read_response(self):
        response = []
        while True:
            part = self.read_response_part()
            response += part
            if (self.process.cur_line.endswith("> ")):
                break
        print("Current Line : ", self.process.cur_line)
        return response

    def parse_output(self, str):
        parseEx = "\[(.+):(.+):(\d+)-(\d+)\]"
        parseEx2 = "\[(.+):\((.+),(.+)\)-\((.+),(.+)\)]"
        m = re.search(parseEx, str)
        if m:
            file, line, start, end = m.groups()
            return file, line, start, line, end
        else:
            m = re.search(parseEx2, str)
            if m:
                file, l1, p1, l2, p2 = m.groups()
                return file, l1, p1, l2, p2
            else:
                return None,0,0,0,0

    def single_step(self, view):
        self.send_command(":step")
        fileName, l1, p1, l2, p2 = self.parse_output(self.process.cur_line)
        if fileName:
            # Could have changed files
            if (fileName != self.file):
                self.file = fileName
                path = os.path.join(self.paths[0], fileName)
                view.run_command("replace_contents", {"path": path})
            self.highlight_selection(view, l1, p1, l2, p2)
        else:
            view.erase_regions(_debuggerRegion)


debugger = Debugger()

class DebugCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        debugger.open(self.view)


class StepCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        debugger.single_step(self.view)



