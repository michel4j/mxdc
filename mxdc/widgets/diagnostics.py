from bcm.device import diagnostics
from bcm.utils.log import get_module_logger
from mxdc.utils import gui
from twisted.python.components import globalRegistry
import gtk
import os

# setup module logger with a default do-nothing handler
_logger = get_module_logger('mxdc')
try:
    import pynotify
    pynotify.init('MxDC')
    _NOTIFY_AVAILABLE = True
except:
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

class DiagnosticDisplay(gtk.Alignment):
    def __init__(self, diag):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/diagnostics'), 
                                  'status_widget')
        self._diagnostic = diag
        self.label.set_markup("<span color='#444647'><b>%s</b></span>" % self._diagnostic.description)
        
        self._diagnostic.connect('status', self.on_status_changed)
        self._status = (diagnostics.DIAG_STATUS_UNKNOWN, "")
        self.icon.set_from_stock('mxdc-dunknown', gtk.ICON_SIZE_MENU)
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
        self.icon.set_from_stock(MSG_ICONS.get(data[0], 'mxdc-unknown'), gtk.ICON_SIZE_MENU)        
        self.info.set_markup('<span color="%s">%s</span>' % (MSG_COLORS.get(_state, 'black'), _msg))
        self.info.set_alignment(1.0, 0.5)

        # Only show notification if state *changes* to bad
        if _state == diagnostics.DIAG_STATUS_BAD:
            if self._status[0] not in [diagnostics.DIAG_STATUS_BAD, diagnostics.DIAG_STATUS_UNKNOWN]:
                self._show_notification(data)
        self._status = data

    def _show_notification(self, data):
        if _NOTIFY_AVAILABLE:
            self._notice = pynotify.Notification(self._diagnostic.description,
                                      data[1])
            self._notice.set_urgency(pynotify.URGENCY_CRITICAL)
            self._notice.set_timeout(20000) # 20 seconds
            self._notice.show()

        
        

class DiagnosticsViewer(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self, False, 3)
        self._num = 0
        #fetch and add diagnostics
        _dl = globalRegistry.subscriptions([], diagnostics.IDiagnostic)
        for diag in _dl:
            self.add_diagnostic(diag)
        self.set_border_width(24)
        self.pack_end(gtk.Label(''), expand=True, fill=True)
        self.show_all()
        


    def add_diagnostic(self, diag):
        if self._num > 0:
            hs = gtk.HSeparator()
            hs.set_sensitive(False)
            self.pack_start(hs, expand=False, fill=False)
        self.pack_start(DiagnosticDisplay(diag), expand=False, fill=False)
        self._num += 1
        