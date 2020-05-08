
from gi.repository import Gtk, Gdk
from mxdc.devices.diagnostics import Diagnostic
from mxdc.devices.interfaces import IDiagnostic
from mxdc.utils import gui
from mxdc import Registry
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

ICON_COLORS = {
    Diagnostic.State.BAD: '#d9534f',
    Diagnostic.State.WARN: '#b46513',
    Diagnostic.State.GOOD: '#437F3F',
    Diagnostic.State.UNKNOWN: '#5bc0de',
    Diagnostic.State.DISABLED: '#636c72',
}

MSG_ICONS = {
    Diagnostic.State.BAD: 'dialog-error-symbolic',
    Diagnostic.State.WARN: 'dialog-warning-symbolic',
    Diagnostic.State.GOOD: 'object-select-symbolic',
    Diagnostic.State.UNKNOWN: 'dialog-question-symbolic',
    Diagnostic.State.DISABLED: 'changes-prevent-symbolic',
}


class DiagnosticDisplay(Gtk.Alignment, gui.BuilderMixin):
    gui_roots = {
        'data/diagnostics': ['status_widget']
    }

    def __init__(self, diagnostic, notifier=None):
        super(DiagnosticDisplay, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self.setup_gui()
        self.diagnostic = diagnostic
        self.label.set_text(self.diagnostic.description)

        color = Gdk.RGBA()
        color.parse(ICON_COLORS[Diagnostic.State.UNKNOWN])
        self.icon.set_from_icon_name(MSG_ICONS[Diagnostic.State.UNKNOWN], Gtk.IconSize.SMALL_TOOLBAR)
        self.icon.override_color(Gtk.StateFlags.NORMAL, color)
        self.info.override_color(Gtk.StateFlags.NORMAL, color)
        self.add(self.status_widget)
        self.notifier = notifier
        self.last_state = self.diagnostic.props.state
        self.info.get_style_context().add_class('diagnostics')
        self.show_all()

        self.diagnostic.connect('notify::state', self.on_state_changed)
        self.diagnostic.connect('notify::message', self.on_message_changed)

    def on_message_changed(self, *args, **kwargs):
        self.info.set_text(self.diagnostic.props.message)
        self.info.set_tooltip_text(self.diagnostic.props.message)
        if self.diagnostic.state == Diagnostic.State.BAD:
            # Only show notification if state *changes* to bad
            self.notifier.notify('{}: {}'.format(self.diagnostic.description, self.diagnostic.message))

    def on_state_changed(self, *args, **kwargs):
        state = self.diagnostic.props.state
        color = Gdk.RGBA()
        color.parse(ICON_COLORS[state])
        self.icon.set_from_icon_name(MSG_ICONS.get(state, 'dialog-question-symbolic'), Gtk.IconSize.SMALL_TOOLBAR)
        self.icon.override_color(Gtk.StateFlags.NORMAL, color)
        self.info.override_color(Gtk.StateFlags.NORMAL, color)
        self.last_state = state


class DiagnosticsController(object):
    def __init__(self, app_window, container):
        super().__init__()
        self.app = app_window
        self.container = container

        # fetch and add diagnostics
        self.diagnostics = [
            DiagnosticDisplay(diagnostic, self.app.notifier)
            for diagnostic in Registry.get_subscribers(IDiagnostic)
        ]
        for diagnostic in self.diagnostics:
            self.container.add(diagnostic)

        self.container.show_all()
