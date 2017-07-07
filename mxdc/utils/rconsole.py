#!/usr/bin/env python
"""Multithreaded interactive interpreter 
Based on interactive interpreter by Fernando Perez

Threading code inspired by:
http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/65109, by Brian
McErlean and John Finlay.

Matplotlib support taken from interactive.py in the matplotlib distribution.

Also borrows liberally from code.py in the Python standard library."""

__author__ = "Fernando Perez, Michel Fodje"
import warnings
warnings.simplefilter("ignore")

import sys
import os
import code
import threading
import time
from gi.repository import Gtk, Gdk
from gi.repository import GObject
import Queue
try:
    import readline
except ImportError:
    has_readline = False
else:
    has_readline = True

class MTConsole(code.InteractiveConsole):
    """Simple multi-threaded shell"""

    def __init__(self,on_kill=None,*args,**kw):
        code.InteractiveConsole.__init__(self,*args,**kw)
        self.code_queue = Queue.Queue(1)
        self._kill = False
        if on_kill is None:
            on_kill = []
        # Check that all things to kill are callable:
        for _ in on_kill:
            if not callable(_):
                raise TypeError,'on_kill must be a list of callables'
        self.on_kill = on_kill
        # Set up tab-completer
        if has_readline:
            import rlcompleter
            try:  # this form only works with python 2.3
                self.completer = rlcompleter.Completer(self.locals)
            except: # simpler for py2.2
                self.completer = rlcompleter.Completer()
                
            readline.set_completer(self.completer.complete)
            # Use tab for completions
            #readline.parse_and_bind('tab: complete')
            # This forces readline to automatically print the above list when tab
            # completion is set to 'complete'.
            readline.parse_and_bind('set show-all-if-ambiguous on')
            # Bindings for incremental searches in the history. These searches
            # use the string typed so far on the command line and search
            # anything in the previous input history containing them.
            readline.parse_and_bind('"\C-r": reverse-search-history')
            readline.parse_and_bind('"\C-s": forward-search-history')

    def runsource(self, source, filename="<input>", symbol="single"):
        """Compile and run some source in the interpreter.

        Arguments are as for compile_command().

        One several things can happen:

        1) The input is incorrect; compile_command() raised an
        exception (SyntaxError or OverflowError).  A syntax traceback
        will be printed by calling the showsyntaxerror() method.

        2) The input is incomplete, and more input is required;
        compile_command() returned None.  Nothing happens.

        3) The input is complete; compile_command() returned a code
        object.  The code is executed by calling self.runcode() (which
        also handles run-time exceptions, except for SystemExit).

        The return value is True in case 2, False in the other cases (unless
        an exception is raised).  The return value can be used to
        decide whether to use sys.ps1 or sys.ps2 to prompt the next
        line.
        """
        try:
            code = self.compile(source, filename, symbol)
        except (OverflowError, SyntaxError, ValueError):
            # Case 1
            self.showsyntaxerror(filename)
            return False

        if code is None:
            # Case 2
            return True

        # Case 3
        # Store code in self, so the execution thread can handle it
        self.code_queue.put(code, block=True)
        while not self.code_queue.empty():
            time.sleep(0.001)
        return False

    def runcode(self):
        """Execute a code object.

        When an exception occurs, self.showtraceback() is called to display a
        traceback."""

        if self._kill:
            print 'Closing threads...',
            sys.stdout.flush()
            for tokill in self.on_kill:
                tokill()
            print 'Done.'
        if not self.code_queue.empty():
            ccode = self.code_queue.get()
            code.InteractiveConsole.runcode(self, ccode )
        return True

    def kill (self):
        """Kill the thread, returning when it has been shut down."""
        self._kill = True

class GTKInterpreter(threading.Thread):
    """Run a gtk mainloop() in a separate thread.
    Python commands can be passed to the thread where they will be executed.
    This is implemented by periodically checking for passed code using a
    GTK timeout callback.
    """
    TIMEOUT = 100 # Milisecond interval between timeouts.
    
    def __init__(self,banner=None):
        threading.Thread.__init__(self)
        self.banner = banner
        self.shell = MTConsole(on_kill=[Gtk.main_quit])

    def run(self):
        self.pre_interact()
        self.shell.interact(self.banner)
        self.shell.kill()

    def mainloop(self):
        self.start()
        GObject.timeout_add(self.TIMEOUT, self.shell.runcode)
        try:
            if Gtk.gtk_version[0] >= 2:
                Gdk.threads_init()          
            if Gtk.gtk_version >= (2, 18):
                Gtk.set_interactive(False)
        except AttributeError:
            pass
        Gtk.main()
        self.join()

    def pre_interact(self):
        """This method should be overridden by subclasses.

        It gets called right before interact(), but after the thread starts.
        Typically used to push initialization code into the interpreter"""
        
        pass

class BeamlineConsole(GTKInterpreter):
    def __init__(self, banner=None):
        banner = (
            "Interactive Beamline Console \n"
            "Python {} \n"
            "Beamline Config: {} \n"
        ).format(sys.version.split('\n')[0], os.environ['MXDC_CONFIG'])
               
        GTKInterpreter.__init__(self, banner)
    
    def pre_interact(self):
        # Code to execute in user's namespace
        push = self.shell.push
        lines = ["import os, sys",
                 "from mxdc.beamline.mx import MXBeamline",
                 "from mxdc.engine.scripting import *",
                 "from mxdc.engine.scanning import *",
                 "from mxdc.engine.fitting import *",
                 "from mxdc.widgets.plotter import ScanPlotter",
                 "beamline = MXBeamline(console=True)",
                 "bl = beamline",
                 "plot = ScanPlotter()",
                 ]
        map(push,lines)
        


if __name__ == '__main__':
    try:
        BeamlineConsole().mainloop()
    finally:
        print 'Quiting...'

