'''
Created on Jan 15, 2010

@author: michel
'''

import threading
from bcm.protocol.ca import threads_init

def async(f):
    """ Run the specified function asynchronously in a thread. Return values will not be available"""
    def new_f(*args, **kwargs):
        threads_init() # enable epics environment to be active within thread
        return f(*args,**kwargs)
        
    def _f(*args, **kwargs):
        threading.Thread(target=new_f, args=args, kwargs=kwargs).start()
    _f.__name__ = f.__name__
    return _f

        