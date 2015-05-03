from mxdc.device import diagnostics
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from twisted.python.components import globalRegistry
from gi.repository import Gtk
import os

# setup module logger with a default do-nothing handler
_logger = get_module_logger('mxdc')
try:
    from gi.repository import Notify
    Notify.init('MxDC')
    _NOTIFY_AVAILABLE = True
except:
    _NOTIFY_AVAILABLE = False
    _logger.warn('System notifications will not be available.')

MSG_COLORS = {
    diagnostics.DIAG_STATUS_BAD: '#9a2b2b',
    diagnostics.DIAG_STATUS_WARN: '#8a8241',
    diagnostics.DIAG_STATUS_GOOD: '#396b3b',
    diagnostics.DIAG_STATUS_UNKNOWN: '#2d6294',
    diagnostics.DIAG_STATUS_DISABLED: '#8a8241',
}

MSG_ICONS = {
    diagnostics.DIAG_STATUS_BAD: 'mxdc-dbad',
    diagnostics.DIAG_STATUS_WARN: 'mxdc-dwarn',
    diagnostics.DIAG_STATUS_GOOD: 'mxdc-dgood',
    diagnostics.DIAG_STATUS_UNKNOWN: 'mxdc-dunknown',
    diagnostics.DIAG_STATUS_DISABLED: 'mxdc-ddisabled',
}

class DiagnosticDisplay(Gtk.Alignment):
    def __init__(self, diag):
        super(DiagnosticDisplay, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/diagnostics'), 
                                  'status_widget')
        self._diagnostic = diag
        self.label.set_markup("<span color='#444647'><b>%s</b></span>" % self._diagnostic.description)
        
        self._diagnostic.connect('status', self.on_status_changed)
        self._status = (diagnostics.DIAG_STATUS_UNKNOWN, "")
        self.icon.set_from_stock('mxdc-dunknown', Gtk.IconSize.MENU)
        self.add(self.status_widget)
        self._notice = None
        self._notify_id = None
        self.show_all()
        
    def __getattr__(self, key):
        try:
            return super(DiagnosticDisplay).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def on_status_changed(self, obj, data):
        if data == self._status:
            return
        
        # Set Icon and message
        _state, _msg = data 
        self.icon.set_from_stock(MSG_ICONS.get(data[0], 'mxdc-unknown'), Gtk.IconSize.MENU)        
        self.info.set_markup('<span color="%s">%s</span>' % (MSG_COLORS.get(_state, 'black'), _msg))
        self.info.set_alignment(1.0, 0.5)

        # Only show notification if state *changes* to bad
        if _state == diagnostics.DIAG_STATUS_BAD:
            if self._status[0] not in [diagnostics.DIAG_STATUS_BAD, diagnostics.DIAG_STATUS_UNKNOWN]:
                self._show_notification(data)
        self._status = data

    def _show_notification(self, data):
        if _NOTIFY_AVAILABLE:
            self._notice = Notify.Notification(self._diagnostic.description,
                                      data[1])
            self._notice.set_urgency(Notify.URGENCY_CRITICAL)
            self._notice.set_timeout(6000) # 20 seconds
            try:
                self._notice.show()
            except:
                _logger.warn(self._diagnostic.description)

        
        

class DiagnosticsViewer(Gtk.Alignment):
    def __init__(self):
        super(DiagnosticsViewer, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self.box = Gtk.VBox(False, 2)
        self.add(self.box)
        self._num = 0
        #fetch and add diagnostics
        _dl = globalRegistry.subscriptions([], diagnostics.IDiagnostic)
        for diag in _dl:
            self.add_diagnostic(diag)
        self.set_border_width(12)
        self.show_all()
        


    def add_diagnostic(self, diag):
        if self._num > 0:
            hs = Gtk.HSeparator()
            hs.set_size_request(-1,3)
            self.box.pack_start(hs, False, False, 0)
        self.box.pack_start(DiagnosticDisplay(diag), True, True, 0)
        self._num += 1
        