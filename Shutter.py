#!/usr/bin/env python

import sys, time
import gtk
import EpicsCA
from LogServer import LogServer

class AbstractShutter:
    def __init__(self, name=None):
        self.state = True
        self.name = name

    def open(self):
        self.state = True
        LogServer.log( "%s opened" % self.name)        
            
    def close(self):
        self.state = False
        LogServer.log( "%s closed" % self.name)        

    def is_open(self):
        return self.state

    def get_name(self):
        return self.name

FakeShutter = AbstractShutter


