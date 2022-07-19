import epics
from gepics import *   # Use pyepics
#from .oepics import *   # use built-in epics interface

def poll(evt=1e-5, iot=1):
    return epics.poll(evt=evt, iot=iot)