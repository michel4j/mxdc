import os

from gi.repository import Gtk, GLib
from gi.repository import Pango

try:
    from mxdc.conf import settings
    DEFAULT_DIRECTORY = os.path.join(os.environ['HOME'], settings.get_session())
except Exception:
    DEFAULT_DIRECTORY = os.environ['HOME']


MAIN_WINDOW = None

BUTTON_TYPES = {
    Gtk.ButtonsType.NONE: (),
    Gtk.ButtonsType.OK: (Gtk.STOCK_OK, Gtk.ResponseType.OK,),
    Gtk.ButtonsType.CLOSE: (Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE,),
    Gtk.ButtonsType.CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,),
    Gtk.ButtonsType.YES_NO: (Gtk.STOCK_NO, Gtk.ResponseType.NO, Gtk.STOCK_YES, Gtk.ResponseType.YES),
    Gtk.ButtonsType.OK_CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK),
}


def make_dialog(dialog_type, title, sub_header=None, details=None, buttons=Gtk.ButtonsType.OK, default=-1,
                extra_widgets=None, parent=None, modal=True):
    msg_dialog = Gtk.MessageDialog(MAIN_WINDOW, 0, dialog_type, Gtk.ButtonsType.NONE, title)
    msg_dialog.set_modal(modal)
    if isinstance(buttons, tuple):
        for button in buttons:
            if len(button) == 3:
                text, response, tooltip = button
            else:
                text, response = button
                tooltip = None
            btn = msg_dialog.add_button(text, response)
            if tooltip:
                btn.set_tooltip_text(tooltip)
    else:
        msg_dialog.add_buttons(*BUTTON_TYPES[buttons])
    if sub_header:
        msg_dialog.format_secondary_markup(sub_header)
    return msg_dialog


def exception_dialog(title, message=None, details=None, buttons=Gtk.ButtonsType.OK):
    msg_dialog = Gtk.MessageDialog(MAIN_WINDOW, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.NONE, title)
    if isinstance(buttons, tuple):
        for button in buttons:
            if len(button) == 3:
                text, response, tooltip = button
            else:
                text, response = button
                tooltip = None
            btn =  msg_dialog.add_button(text, response)
            if tooltip:
                btn.set_tooltip_text(tooltip)
    else:
        msg_dialog.add_buttons(*BUTTON_TYPES[buttons])
    if message:
        msg_dialog.format_secondary_markup(message)
    if details:
        content_area = msg_dialog.get_content_area()
        view = Gtk.TextView()
        view.get_buffer().set_text(details)
        view.modify_font(Pango.FontDescription('monospace 7'))
        view.set_editable(False)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        sw.add(view)
        sw.set_size_request(-1, 150)
        sw.show_all()
        content_area.pack_start(sw, True, True, 0)
    return msg_dialog


class Timer(object):
    """
    An object used for displaying countdown timers and destroying dialogs after a given amount of time.
    """
    def __init__(self, countdown, dialog):
        self.countdown = countdown
        self.label = dialog.get_message_area().get_children()[-1]
        self.dialog = dialog

    def __call__(self):
        self.countdown -= 1
        self.label.set_text(f'{self.countdown} seconds')
        if self.countdown <= 0:
            self.dialog.destroy()
        return self.countdown > 0


def simple_dialog(*args, **kwargs):
    countdown = kwargs.pop('countdown', None)
    msg_dialog = make_dialog(*args, **kwargs)
    if countdown is not None:
        GLib.timeout_add(1000, Timer(countdown, msg_dialog))

    result = msg_dialog.run()
    msg_dialog.destroy()
    return result


def error(*args, **kwargs):
    return simple_dialog(Gtk.MessageType.ERROR, *args, **kwargs)


def info(*args, **kwargs):
    return simple_dialog(Gtk.MessageType.INFO, *args, **kwargs)


def warning(*args, **kwargs):
    return simple_dialog(Gtk.MessageType.WARNING, *args, **kwargs)


def question(*args, **kwargs):
    return simple_dialog(Gtk.MessageType.QUESTION, *args, **kwargs)


def yesno(*args, **kwargs):
    kwargs['buttons'] = kwargs.get('buttons') or (('Yes', Gtk.ResponseType.YES), ('No', Gtk.ResponseType.NO))
    kwargs['default'] = kwargs.get('default') or Gtk.ResponseType.YES
    return simple_dialog(Gtk.MessageType.QUESTION, *args, **kwargs)


def check_folder(directory, parent=None, warn=True):
    if directory is None:
        return False
    if not os.path.exists(directory):
        header = "The folder '%s' does not exist!" % directory
        sub_header = "Please select a valid folder and try again."
        if warn:
            warning(header, sub_header, parent=parent)
        return False
    elif not os.access(directory, os.W_OK):
        header = "The folder %s can not be written to!" % directory
        sub_header = "Please select a valid folder and try again."
        if warn:
            warning(header, sub_header, parent=parent)
        return False
    return True


def select_opensave_file(title, action, parent=None, filters=[], formats=[], default_folder=None):
    if action in [Gtk.FileChooserAction.OPEN, Gtk.FileChooserAction.SELECT_FOLDER, Gtk.FileChooserAction.CREATE_FOLDER]:
        _stock = Gtk.STOCK_OPEN
    else:
        _stock = Gtk.STOCK_SAVE
    dialog = Gtk.FileChooserDialog(
        title=title,
        action=action,
        parent=parent,
        buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, _stock, Gtk.ResponseType.OK))
    if default_folder is None:
        dialog.set_current_folder(DEFAULT_DIRECTORY)
    else:
        dialog.set_current_folder(default_folder)
    dialog.set_do_overwrite_confirmation(True)
    if action == Gtk.FileChooserAction.OPEN:
        for name, patterns in filters:
            fil = Gtk.FileFilter()
            fil.set_name(name)
            for pat in patterns:
                fil.add_pattern(pat)
            dialog.add_filter(fil)
    elif action == Gtk.FileChooserAction.SAVE:
        format_info = dict(formats)
        hbox = Gtk.HBox(spacing=10)
        hbox.pack_start(Gtk.Label("Format:"), False, False, 0)
        cbox = Gtk.ComboBoxText()
        hbox.pack_start(cbox, True, True, 0)
        for fmt in formats:
            cbox.append_text(fmt[0])
        cbox.set_active(0)
        hbox.show_all()
        dialog.set_extra_widget(hbox)

        def _cb(obj, dlg, info):
            fname = "%s.%s" % (os.path.splitext(dlg.get_filename())[0],
                               info.get(obj.get_active_text()))
            dlg.set_current_name(os.path.basename(fname))

        cbox.connect('changed', _cb, dialog, format_info)

    if dialog.run() == Gtk.ResponseType.OK:
        filename = dialog.get_filename()
        if action == Gtk.FileChooserAction.SAVE:
            txt = cbox.get_active_text()
            fext = os.path.splitext(filename)[1].lstrip('.').lower()
            if fext == '':
                fext = list(format_info.values())[0]
            fltr = format_info.get(txt, fext)
            filename = "%s.%s" % (os.path.splitext(filename)[0], fltr)
        else:
            fltr = dialog.get_filter()
    else:
        filename = None
        fltr = None
    dialog.destroy()
    return filename, fltr


def select_save_file(title, formats=[], default_folder=None):
    return select_opensave_file(title, Gtk.FileChooserAction.SAVE, parent=MAIN_WINDOW, formats=formats,
                                default_folder=default_folder)


def select_open_file(title, parent=None, filters=[], default_folder=None):
    return select_opensave_file(title, Gtk.FileChooserAction.OPEN, parent=parent, filters=filters,
                                default_folder=default_folder)


def select_open_image(parent=None, default_folder=None):
    filters = [
        ('Diffraction Frames', [
            "*.img", "*.marccd", "*.mccd", "*.pck",
            "*.cbf", "*.h5", "*.osc", "*.[0-9][0-9][0-9]", "*.[0-9][0-9][0-9][0-9]"]
        ),
        ('XDS Spot files', ["SPOT.XDS*"]),
        ('XDS ASCII file', ["X*.HKL*"]),
    ]
    return select_opensave_file('Select Image', Gtk.FileChooserAction.OPEN, parent=parent, filters=filters,
                                default_folder=default_folder)


