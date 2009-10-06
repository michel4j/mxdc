"""This module implements utility classes and functions for logging."""

import logging
import termcolor
import types

LOG_LEVEL = logging.DEBUG

class NullHandler(logging.Handler):

    """A do-nothing log handler."""
    
    def emit(self, record):
        pass

class ColoredConsoleHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if record.levelno == logging.WARNING:
                msg = termcolor.colored(msg, "yellow")
            elif record.levelno > logging.WARNING:
                msg = termcolor.colored(msg, "red")
            elif record.levelno == logging.DEBUG:
                msg = termcolor.colored(msg, "cyan")
            if not hasattr(types, "UnicodeType"): #if no unicode support...
                self.stream.write("%s\n" % msg)
            else:
                try:
                    self.stream.write("%s\n" % msg)
                except UnicodeError:
                    self.stream.write("%s\n" % msg.encode("UTF-8"))
            self.flush()
        except:
            self.handleError(record)

def get_module_logger(name):
    """A factory which creates loggers with the given name and returns it."""
    
    _logger = logging.getLogger(name)
    _logger.setLevel(LOG_LEVEL)
    _logger.addHandler( NullHandler() )
    return _logger



def log_to_console(level=logging.DEBUG):
    """Add a log handler which logs to the console."""
    
    console = ColoredConsoleHandler()
    console.setLevel(level)
    formatter = logging.Formatter('%(name)s|%(asctime)s| %(message)s', '%d/%m/%y %H:%M:%S')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def log_to_file(filename, level=logging.DEBUG):
    """Add a log handler which logs to the console."""    
    logfile = logging.FileHandler(filename)
    logfile.setLevel(level)
    formatter = logging.Formatter('%(name)s|%(asctime)s| %(message)s', '%d/%m/%y %H:%M:%S')
    logfile.setFormatter(formatter)
    logging.getLogger('').addHandler(logfile)
      