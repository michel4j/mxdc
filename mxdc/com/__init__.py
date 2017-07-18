from mxdc.interface.com import IProcessVariable
from gi.repository import GObject       # @UnresolvedImport
from zope.interface import implements   # @UnresolvedImport

class BasePV(GObject.GObject):
    implements(IProcessVariable)
    __gsignals__ = {
        'changed':      (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        'time':         (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        'active' :      (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,)),
        'alarm' :       (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,))
    }
    
    def __init__(self, name, monitor=True, timed=False):
        GObject.GObject.__init__(self)

    def set_state(self, **kwargs):
        for st, val in kwargs.items():
            st = st.replace('_', '-')
            self.state_info.update({st: val})
            GObject.idle_add(self.emit, st, val)

    def do_changed(self, arg):
        pass
    
    def do_time(self, arg):
        pass
    
    def do_active(self, arg):
        pass
    
    def do_alarm(self, arg):
        pass
