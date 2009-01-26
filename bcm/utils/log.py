"""This module implements utility classes and functions for logging."""

import logging

LOG_LEVEL = logging.DEBUG

class NullHandler(logging.Handler):

    """A do-nothing log handler."""
    
    def emit(self, record):
        pass

def get_module_logger(name):
    """A factory which creates loggers with the given name and returns it."""
    
    _logger = logging.getLogger(__name__)
    _logger.setLevel(LOG_LEVEL)
    _logger.addHandler( NullHandler() )
    return _logger

