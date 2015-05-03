"""This module implements utility classes and functions for logging."""

from twisted.python import log
import logging
import os
import termcolor
import types

if os.environ.get('MXDC_DEBUG', '0') in ['1', 'True', 'TRUE', 'true']:
    LOG_LEVEL = logging.DEBUG
else:   
    LOG_LEVEL = logging.INFO

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
                self.stream.write("%s\n" % msg)
            self.flush()
        except:
            self.handleError(record)

class TwistedLogHandler(logging.StreamHandler):
    def emit(self, record):
        msg = self.format(record)
        if record.levelno == logging.WARNING:
            log.msg(msg)
        elif record.levelno > logging.WARNING:
            log.err(msg)
        else:
            log.msg(msg)
        self.flush()

def get_module_logger(name):
    """A factory which creates loggers with the given name and returns it."""
    name = name.split('.')[-1]
    _logger = logging.getLogger(name)
    _logger.setLevel(LOG_LEVEL)
    _logger.addHandler( NullHandler() )
    return _logger



def log_to_console(level=LOG_LEVEL):
    """Add a log handler which logs to the console."""
    
    console = ColoredConsoleHandler()
    console.setLevel(level)
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def log_to_twisted(level=LOG_LEVEL):
    """Add a log handler which logs to the twisted logger."""
    
    console = TwistedLogHandler()
    console.setLevel(level)
    formatter = logging.Formatter('%(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def log_to_file(filename, level=logging.DEBUG):
    """Add a log handler which logs to the console."""    
    logfile = logging.FileHandler(filename)
    logfile.setLevel(level)
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
    logfile.setFormatter(formatter)
    logging.getLogger('').addHandler(logfile)
      

log_to_console()