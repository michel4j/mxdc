#import ca
import thread, time
from Ezca import *
import EpicsCA

EZ = Ezca()
lock = thread.allocate_lock()
def myget(pv):
    lock.acquire()
    val = EZ.caget(pv)
    lock.release()
    return val
    
def myput(pv,val):
    lock.acquire()
    EZ.caput(pv, val)
    lock.release()
    
class PV:
    def __init__(self, name):
        self.name = name
        
    def get(self):
        value = myget(self.name)
        return value
        
    def put(self, val):
        myput(self.name, val)
        
#PV = EpicsCA.PV
