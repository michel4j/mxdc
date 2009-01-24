"""This module implements utility classes and functions for logging."""

import logging

class NullHandler(logging.Handler):

    """A do-nothing log handler."""
    
    def emit(self, record):
        pass

