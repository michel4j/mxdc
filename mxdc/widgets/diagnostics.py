from mxdc.device import diagnostics
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from twisted.python.components import globalRegistry
from gi.repository import Gtk, Gdk

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)
try:
    from gi.repository import Notify

    Notify.init('MxDC')
    _NOTIFY_AVAILABLE = True
except:
    _NOTIFY_AVAILABLE = False
    logger.warn('System notifications will not be available.')

ICON_COLORS = {
    diagnostics.DIAG_STATUS_BAD: '#d9534f',
    diagnostics.DIAG_STATUS_WARN: '#f0ad4e',
    diagnostics.DIAG_STATUS_GOOD: '#5cb85c',
    diagnostics.DIAG_STATUS_UNKNOWN: '#5bc0de',
    diagnostics.DIAG_STATUS_DISABLED: '#636c72',
}
MSG_COLORS = {
    diagnostics.DIAG_STATUS_BAD: '#9a2b2b',
    diagnostics.DIAG_STATUS_WARN: '#8a8241',
    diagnostics.DIAG_STATUS_GOOD: '#396b3b',
    diagnostics.DIAG_STATUS_UNKNOWN: '#2d6294',
    diagnostics.DIAG_STATUS_DISABLED: '#8a8241',
}

MSG_ICONS = {
    diagnostics.DIAG_STATUS_BAD: 'dialog-error-symbolic',
    diagnostics.DIAG_STATUS_WARN: 'dialog-warning-symbolic',
    diagnostics.DIAG_STATUS_GOOD: 'object-select-symbolic',
    diagnostics.DIAG_STATUS_UNKNOWN: 'dialog-question-symbolic',
    diagnostics.DIAG_STATUS_DISABLED: 'touchpad-disabled-symbolic',
}


class DiagnosticDisplay(Gtk.Alignment, gui.BuilderMixin):
    gui_roots = {
        'data/diagnostics': ['status_widget']
    }

    def __init__(self, diag):
        super(DiagnosticDisplay, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self.setup_gui()
        self._diagnostic = diag
        self.label.set_markup("<span color='#444647'><b>%s</b></span>" % self._diagnostic.description)

        self._diagnostic.connect('status', self.on_status_changed)
        self._status = (diagnostics.DIAG_STATUS_UNKNOWN, "")

        color = Gdk.RGBA()
        color.parse(ICON_COLORS[diagnostics.DIAG_STATUS_UNKNOWN])
        self.override_color(Gtk.StateFlags.NORMAL, color)
        self.icon.set_from_icon_name(MSG_ICONS[diagnostics.DIAG_STATUS_UNKNOWN], Gtk.IconSize.SMALL_TOOLBAR)

        self.add(self.status_widget)
        self._notice = None
        self._notify_id = None
        self.show_all()

    def on_status_changed(self, obj, data):
        if data == self._status:
            return

        # Set Icon and message
        _state, _msg = data
        color = Gdk.RGBA()
        color.parse(ICON_COLORS[_state])
        self.icon.set_from_icon_name(MSG_ICONS.get(_state, 'dialog-question-symbolic'), Gtk.IconSize.SMALL_TOOLBAR)
        self.override_color(Gtk.StateFlags.NORMAL, color)
        self.info.set_markup('<span color="%s">%s</span>' % (MSG_COLORS.get(_state, 'black'), _msg))
        self.info.set_alignment(1.0, 0.5)

        # Only show notification if state *changes* to bad
        if _state == diagnostics.DIAG_STATUS_BAD:
            if self._status[0] not in [diagnostics.DIAG_STATUS_BAD, diagnostics.DIAG_STATUS_UNKNOWN]:
                self._show_notification(data)
        self._status = data

    def _show_notification(self, data):
        if _NOTIFY_AVAILABLE:
            self._notice = Notify.Notification(
                summary=self._diagnostic.description, app_name='MxDC', body=data[1], icon_name=MSG_ICONS[data[0]]
            )
            self._notice.set_urgency(Notify.Urgency.NORMAL)
            self._notice.set_timeout(6000)  # 20 seconds
            try:
                self._notice.show()
            except:
                logger.warn(self._diagnostic.description)


class DiagnosticsViewer(Gtk.Alignment):
    def __init__(self):
        super(DiagnosticsViewer, self).__init__()
        self.set(0.5, 0.5, 1, 0.75)
        self.box = Gtk.FlowBox(column_spacing=12, row_spacing=6)
        self.box.set_valign(Gtk.Align.START)
        self.box.set_max_children_per_line(2)
        self.box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.add(self.box)
        self._num = 0
        # fetch and add diagnostics
        _dl = globalRegistry.subscriptions([], diagnostics.IDiagnostic)
        for diag in _dl:
            self.add_diagnostic(diag)
        self.set_border_width(12)
        self.show_all()

    def add_diagnostic(self, diag):
        self.box.add(DiagnosticDisplay(diag))
        self._num += 1
