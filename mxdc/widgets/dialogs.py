import fnmatch
import os
from pathlib import Path
from typing import Sequence, Union, Tuple, Any

from gi.repository import Gtk, GLib
from gi.repository import Pango

MAIN_WINDOW = None

BUTTON_TYPES = {
    Gtk.ButtonsType.NONE: (),
    Gtk.ButtonsType.OK: (Gtk.STOCK_OK, Gtk.ResponseType.OK,),
    Gtk.ButtonsType.CLOSE: (Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE,),
    Gtk.ButtonsType.CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,),
    Gtk.ButtonsType.YES_NO: (Gtk.STOCK_NO, Gtk.ResponseType.NO, Gtk.STOCK_YES, Gtk.ResponseType.YES),
    Gtk.ButtonsType.OK_CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK),
}


class SmartFilter(Gtk.FileFilter):
    def __init__(self, name: str = 'All', patterns: Sequence[str] = ('*',), extension: Union[str, None] = None):
        """
        Create a File filter from a name and sequence of patterns
        :param name: Filter name
        :param patterns: file patterns to match
        :param extension: optional file extension to be used for file save formatting.
        """
        super().__init__()

        self.set_name(name)
        self.patterns = patterns
        self.extension = extension
        for pattern in patterns:
            self.add_pattern(pattern)
        if extension:
            self.add_pattern(f'*.{extension}')

    def match(self, file_name: str) -> bool:
        """
        Check if a file_name matches this filter
        :param file_name:
        :return: True if it matches
        """
        return any(fnmatch.fnmatch(file_name, pattern) for pattern in self.patterns)

    def update_file_name(self, file_name: str) -> str:
        """
        Update the filename replacing the extension to match the current filter. Mainly useful
        when saving a file.

        :param file_name: File name to update
        :return: new filename with extension replaced or the same file name if no extension is set
        """
        if self.extension:
            main, ext = os.path.splitext(file_name)
            file_name = f"{main}.{self.extension}"

        return file_name


class FileDialog:
    directory: Path

    def __init__(self):
        self.set_folder(os.environ.get('HOME', ""))

    def set_folder(self, directory: os.PathLike):
        self.directory = Path(directory)

    @staticmethod
    def on_format_changed(obj: Any, dialog: Gtk.FileChooserDialog, filters: Sequence[SmartFilter]):
        """
        Callback called when the format is changed in save mode. Not meant to be called directly
        :param obj: Object which emitted the signal
        :param dialog: File Chooser dialog
        :param filters: Sequence of Smart Filters format
        """
        current_file_name = dialog.get_filename()
        active = obj.get_active()
        if active >=0 and filters and current_file_name and current_file_name.strip():
            updated_file_name = filters[active].update_file_name(dialog.get_filename())
            dialog.set_current_name(os.path.basename(updated_file_name))

        return True

    def select_to_open(
        self,
        title: str,
        filters: Sequence[Gtk.FileFilter] = (),
        multiple: bool = False
    ) -> Union[Sequence[str], os.PathLike]:
        """
        Select a file for opening
        :param title: Title of File Chooser
        :param filters: Optional sequence of file filters
        :param multiple: Whether to select multiple files
        :return: A single selected file, or a sequence of file names if multiple is True,
        None, if the dialog was cancelled.
        """

        dialog = Gtk.FileChooserDialog(
            title=title, action=Gtk.FileChooserAction.OPEN, parent=MAIN_WINDOW,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK),
            select_multiple=multiple
        )
        #dialog.set_current_folder(str(self.directory))

        for file_filter in filters:
            dialog.add_filter(file_filter)

        if dialog.run() == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            filename = dialog.get_filename()
            self.set_folder(Path(filename).parent)
        else:
            filenames = ()
            filename = None

        dialog.destroy()
        return filenames if multiple else filename

    def select_to_save(
        self,
        title: str,
        filters: Sequence[Gtk.FileFilter] = (),
    ) -> Tuple[str, SmartFilter]:
        """
        Select a file for opening
        :param title: Title of File Chooser
        :param filters: Optional sequence of file filters
        :return: A Tuple of filename, and active file format filter,
        """

        dialog = Gtk.FileChooserDialog(
            title=title, action=Gtk.FileChooserAction.SAVE, parent=MAIN_WINDOW,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
        )
        #dialog.set_current_folder(str(self.directory))
        dialog.set_current_name("untitled")
        dialog.set_do_overwrite_confirmation(True)

        # Add File format selectors
        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        format_box.pack_start(Gtk.Label("Format:"), False, False, 0)
        format_combo = Gtk.ComboBoxText()
        format_box.pack_start(format_combo, True, True, 0)
        format_box.show_all()

        if filters:
            for file_filter in filters:
                format_combo.append_text(file_filter.get_name())
            format_combo.set_active(0)
            format_combo.connect('changed', self.on_format_changed, dialog, filters)
        dialog.set_extra_widget(format_box)

        if dialog.run() == Gtk.ResponseType.OK:
            active_filter = max(0, format_combo.get_active())
            file_format = None if not filters else filters(active_filter)
            filename = dialog.get_filename()

            # fix the name if a file_format is provided
            if file_format:
                path = Path(filename)
                filename = str(path.parent / file_format.update_file_name(path.name))
        else:
            filename = None
            file_format = None

        dialog.destroy()
        return filename, file_format


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
            btn = msg_dialog.add_button(text, response)
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


file_chooser = FileDialog()