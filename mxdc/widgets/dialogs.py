import os
import re

from gi.repository import Gtk
from gi.repository import Pango
from mxdc.utils import config

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
                extra_widgets=None, parent=None):
    msg_dialog = Gtk.MessageDialog(MAIN_WINDOW, 0, dialog_type, Gtk.ButtonsType.NONE, title)
    if isinstance(buttons, tuple):
        for button in buttons:
            msg_dialog.add_buttons(*button)
    else:
        msg_dialog.add_buttons(*BUTTON_TYPES[buttons])
    if sub_header:
        msg_dialog.format_secondary_markup(sub_header)
    return msg_dialog


def exception_dialog(title, message=None, details=None, buttons=Gtk.ButtonsType.OK):
    msg_dialog = Gtk.MessageDialog(MAIN_WINDOW, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.NONE, title)
    if isinstance(buttons, tuple):
        for button in buttons:
            msg_dialog.add_buttons(*button)
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


def simple_dialog(*args, **kwargs):
    msg_dialog = make_dialog(*args, **kwargs)
    result = msg_dialog.run()
    msg_dialog.destroy()
    return result


def error(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1,
          extra_widgets=None):
    return simple_dialog(Gtk.MessageType.ERROR, header, sub_header, details, parent=parent,
                         buttons=buttons, default=default, extra_widgets=extra_widgets)


def info(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1,
         extra_widgets=None):
    return simple_dialog(Gtk.MessageType.INFO, header, sub_header, details, parent=parent,
                         buttons=buttons, default=default, extra_widgets=extra_widgets)


def warning(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1,
            extra_widgets=None):
    return simple_dialog(Gtk.MessageType.WARNING, header, sub_header, details, parent=parent,
                         buttons=buttons, default=default, extra_widgets=extra_widgets)


def question(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1,
             extra_widgets=None):
    return simple_dialog(Gtk.MessageType.QUESTION, header, sub_header, details, parent=parent,
                         buttons=buttons, default=default, extra_widgets=extra_widgets)


def yesno(header, sub_header=None, details=None, parent=None, default=Gtk.ResponseType.YES):
    buttons = (
        ('Yes', Gtk.ResponseType.YES),
        ('Yes', Gtk.ResponseType.NO),
    )
    return simple_dialog(Gtk.MessageType.QUESTION, header, sub_header, details, parent=parent,
                         buttons=buttons, default=default, extra_widgets=None)


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
        dialog.set_current_folder(os.path.join(os.environ['HOME'], config.get_session()))
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
                fext = format_info.values()[0]
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
        ('Diffraction Frames',
         ["*.img", "*.marccd", "*.mccd", "*.pck", "*.cbf", "*.[0-9][0-9][0-9]", "*.[0-9][0-9][0-9][0-9]"]),
        ('XDS Spot files', ["SPOT.XDS*", "*.HKL*"]),
        ('All files', ["*.*"])
    ]
    return select_opensave_file('Select Image', Gtk.FileChooserAction.OPEN, parent=parent, filters=filters,
                                default_folder=default_folder)
