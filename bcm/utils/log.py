"""This module implements utility classes and functions for logging."""

import logging

LOG_LEVEL = logging.DEBUG

class NullHandler(logging.Handler):

    """A do-nothing log handler."""
    
    def emit(self, record):
        pass

def get_module_logger(name):
    """A factory which creates loggers with the given name and returns it."""
    
    _logger = logging.getLogger(name)
    _logger.setLevel(LOG_LEVEL)
    _logger.addHandler( NullHandler() )
    return _logger

def log_to_console(level=logging.DEBUG):
    """Add a log handler which logs to the console."""
    
    console = logging.StreamHandler()
    console.setLevel(level)
    formatter = logging.Formatter('%(levelname)s|%(asctime)s|%(name)s: %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    