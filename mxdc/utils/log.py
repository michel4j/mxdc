"""This module implements utility classes and functions for logging."""
import logging
from functools import wraps
from logging.handlers import RotatingFileHandler
from reprlib import aRepr

IMPORTANT = 25
logging.addLevelName(IMPORTANT, 'IMPORTANT')


class TermColor(object):
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    ITALICS = '\033[3m'

    @classmethod
    def bold(cls, text):
        return '{}{}{}'.format(cls.BOLD, text, cls.ENDC)

    @classmethod
    def warn(cls, text):
        return '{}{}{}'.format(cls.WARNING, text, cls.ENDC)

    @classmethod
    def success(cls, text):
        return '{}{}{}'.format(cls.OKGREEN, text, cls.ENDC)

    @classmethod
    def error(cls, text):
        return '{}{}{}'.format(cls.FAIL, text, cls.ENDC)

    @classmethod
    def emphasis(cls, text):
        return '{}{}{}'.format(cls.BOLD, text, cls.ENDC)

    @classmethod
    def debug(cls, text):
        return '{}{}{}'.format(cls.OKBLUE, text, cls.ENDC)

    @classmethod
    def normal(cls, text):
        return text

    @classmethod
    def underline(cls, text):
        return '{}{}{}'.format(cls.UNDERLINE, text, cls.ENDC)

    @classmethod
    def italics(cls, text):
        return '{}{}{}'.format(cls.ITALICS, text, cls.ENDC)


class NullHandler(logging.Handler):
    """A do-nothing log handler."""

    def emit(self, record):
        pass


class ColoredConsoleHandler(logging.StreamHandler):
    def format(self, record):
        msg = super(ColoredConsoleHandler, self).format(record)
        if record.levelno == logging.WARNING:
            msg = TermColor.warn(msg)
        elif record.levelno > logging.WARNING:
            msg = TermColor.error(msg)
        elif record.levelno == logging.DEBUG:
            msg = TermColor.debug(msg)
        return msg


def get_module_logger(name):
    """A factory which creates loggers with the given name and returns it."""
    name = name.split('.')[-1]
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(NullHandler())
    return logger


def log_to_console(level=logging.DEBUG):
    """Add a log handler which logs to the console."""

    console = ColoredConsoleHandler()
    console.setLevel(level)
    if level == logging.DEBUG:
        formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
    else:
        formatter = logging.Formatter('%(asctime)s %(message)s', '%b/%d %H:%M:%S')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)


def log_to_file(filename, level=logging.DEBUG):
    """Add a log handler which logs to the console."""
    logfile = RotatingFileHandler(filename, maxBytes=1000000, backupCount=10)
    logfile.setLevel(level)
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
    logfile.setFormatter(formatter)
    logging.getLogger('').addHandler(logfile)


logger = get_module_logger(__name__)


def log_call(f):
    """
    Log all calls to the function or method
    @param f: function or method
    """

    @wraps(f)
    def _decorator(*args, **kwargs):
        params = [
                     aRepr.repr1(arg, 1) for arg in args[1:]
                 ] + [
                     '{}={}'.format(p[0], aRepr.repr1(p[1], 1)) for p in list(kwargs.items())
                 ]
        logger.debug('<{}({})>'.format(f.__name__, ', '.join(params)))
        return f(*args, **kwargs)

    return _decorator
