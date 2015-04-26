from mxdc.interface.com import IProcessVariable
from gi.repository import GObject       # @UnresolvedImport
from zope.interface import implements   # @UnresolvedImport

class BasePV(GObject.GObject):
    implements(IProcessVariable)
    __gsignals__ = {
        'changed':      (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        'timed-change': (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        'active' :      (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,)),
        'alarm' :       (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,))
    }
    
    def __init__(self, name, monitor=True, timed=False):
        GObject.GObject.__init__(self)
    
    def do_changed(self, arg):
        pass
    
    def do_timed_change(self, arg):
        pass
    
    def do_active(self, arg):
        pass
    
    def do_alarm(self, arg):
        pass
