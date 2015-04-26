'''
Created on Jan 15, 2010

@author: michel
'''

import threading
from mxdc.com.ca import threads_init

def async(f):
    """ Run the specified function asynchronously in a thread. Return values will not be available"""
    def new_f(*args, **kwargs):
        threads_init() # enable epics environment to be active within thread
        return f(*args,**kwargs)
        
    def _f(*args, **kwargs):
        threading.Thread(target=new_f, args=args, kwargs=kwargs).start()
    _f.__name__ = f.__name__
    return _f


def ca_thread_enable(f):
    """ Make sure an active EPICS CA context is available or join one before running"""
    def _f(*args, **kwargs):
        threads_init() 
        return f(*args,**kwargs)
        _f.__name__ = f.__name__
    return _f
    