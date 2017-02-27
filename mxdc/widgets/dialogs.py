import os
from gi.repository import Gtk
from gi.repository import Pango
import re
from mxdc.utils import gui, config

MAIN_WINDOW = None

_IMAGE_TYPES = {
    Gtk.MessageType.INFO: Gtk.STOCK_DIALOG_INFO,
    Gtk.MessageType.WARNING : Gtk.STOCK_DIALOG_WARNING,
    Gtk.MessageType.QUESTION : Gtk.STOCK_DIALOG_QUESTION,
    Gtk.MessageType.ERROR : Gtk.STOCK_DIALOG_ERROR,
}

_BUTTON_TYPES = {
    Gtk.ButtonsType.NONE: (),
    Gtk.ButtonsType.OK: (Gtk.STOCK_OK, Gtk.ResponseType.OK,),
    Gtk.ButtonsType.CLOSE: (Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE,),
    Gtk.ButtonsType.CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,),
    Gtk.ButtonsType.YES_NO: (Gtk.STOCK_NO, Gtk.ResponseType.NO,
                         Gtk.STOCK_YES, Gtk.ResponseType.YES),
    Gtk.ButtonsType.OK_CANCEL: (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                            Gtk.STOCK_OK, Gtk.ResponseType.OK),
    }
    
class AlertDialog(Gtk.Dialog):
    def __init__(self, parent, flags, dialog_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.NONE):
        if not dialog_type in _IMAGE_TYPES:
            raise TypeError(
                "dialog_type must be one of: %s", ', '.join(_IMAGE_TYPES.keys()))
        if not buttons in _BUTTON_TYPES:
            raise TypeError(
                "buttons be one of: %s", ', '.join(_BUTTON_TYPES.keys()))

        super(AlertDialog, self).__init__('', parent, flags)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_border_width(5)
        self.set_resizable(False)
        self.set_title(" ")
        self.set_skip_taskbar_hint(True)

        self._primary_label = Gtk.Label()
        self._secondary_label = Gtk.Label()
        self._image = Gtk.Image.new_from_stock(_IMAGE_TYPES[dialog_type],
                                               Gtk.IconSize.DIALOG)
        self._image.set_alignment(0.5, 0.0)

        self._primary_label.set_use_markup(True)
        for label in (self._primary_label, self._secondary_label):
            label.set_line_wrap(True)
            label.set_selectable(True)
            label.set_alignment(0.0, 0.5)

        hbox = Gtk.HBox(False, 12)
        vbox = Gtk.VBox(False, 12)
        hbox.pack_start(self._image, False, False, 0)
        vbox.pack_start(self._primary_label, False, False, 0)
        vbox.pack_start(self._secondary_label, False, False, 0)
        hbox.pack_start(vbox, False, False, 0)
        hbox.set_border_width(5)
        hbox.show_all()
        
        self.details_buffer = Gtk.TextBuffer()
        self.details_view = Gtk.TextView(self.details_buffer)
        self.details_view.set_editable(False)
        pf = self.details_view.get_pango_context().get_font_description()        
        pf.set_size(int(pf.get_size() * 0.85))
        self.details_view.modify_font(pf)
        
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        sw.add(self.details_view)
        sw.set_size_request(-1, 200)
        
        self._expander = Gtk.Expander("Details")
        self._expander.add(sw)
        self._expander.set_border_width(5)
        self._expander.show_all()
        
        self._expander.hide()
        self._expander.set_expanded(False)
        self._expander.set_spacing(3)
        self.add_buttons(*_BUTTON_TYPES[buttons])
        
        self.vbox.pack_start(hbox, False, False, 0)
        self.vbox.pack_start(self._expander, True, True, 1)
        self.set_default(self.get_action_area())

        
    def set_primary(self, text):
        self._primary_label.set_markup('<span weight="bold" size="large">%s</span>' % text)
        
    def add_widget(self, widget):
        self.vbox.pack_start(widget, False, False, 0)
        
    def set_secondary(self, text):
        self._secondary_label.set_markup(text)

    def set_details(self, text):
        self.details_buffer.set_text(text)
        self._expander.show_all()

class MyDialog(object):
    """Create and show a MessageDialog.

    @param dialog_type: one of constants
      - Gtk.MessageType.INFO
      - Gtk.MessageType.WARNING
      - Gtk.MessageType.QUESTION
      - Gtk.MessageType.ERROR
    @param header:      A header text to be inserted in the dialog.
    @param sub_header:  A longer description of the message
    @param details:     Further details of message.
    @param parent:      The parent widget of this dialog
    @type parent:       a Gtk.Window subclass
    @param buttons:     The button type that the dialog will be display,
      one of the constants:
       - Gtk.ButtonsType.NONE
       - Gtk.ButtonsType.OK
       - Gtk.ButtonsType.CLOSE
       - Gtk.ButtonsType.CANCEL
       - Gtk.ButtonsType.YES_NO
       - Gtk.ButtonsType.OK_CANCEL
      or a tuple or 2-sized tuples representing label and response. If label
      is a stock-id a stock icon will be displayed.
    @param default: optional default response id
    """
    def __init__(self, dialog_type, header, sub_header=None, details=None, parent=None,
                  buttons=Gtk.ButtonsType.OK, default=-1, extra_widgets=None):
        
        if buttons in (Gtk.ButtonsType.NONE, Gtk.ButtonsType.OK, Gtk.ButtonsType.CLOSE,
                       Gtk.ButtonsType.CANCEL, Gtk.ButtonsType.YES_NO,
                       Gtk.ButtonsType.OK_CANCEL):
            dialog_buttons = buttons
            buttons = []
        else:
            dialog_buttons = Gtk.ButtonsType.NONE

        if parent is None:
            parent = MAIN_WINDOW

        self.dialog = AlertDialog(parent=parent, flags=Gtk.DialogFlags.MODAL,
                           dialog_type=dialog_type, buttons=dialog_buttons)
        for text, response in buttons:
            btn = self.dialog.add_button(text, response)
            if response == default:
                self.dialog.set_default(btn)
                btn.set_can_default(True)
                    
        self.dialog.set_primary(header)
        if sub_header:
            self.dialog.set_secondary(sub_header)
            
        if details:
            if isinstance(details, Gtk.Widget):
                self.dialog.set_details_widget(details)
            elif isinstance(details, basestring):
                self.dialog.set_details(details)
    
        if parent:
            self.dialog.set_modal(True)
    
        if extra_widgets:
            for wdg in extra_widgets:
                self.dialog.add_widget(wdg)
                wdg.show()
                
    def __call__(self):
        response = self.dialog.run()
        self.dialog.destroy()
        return response

    def show(self):
        self.dialog.show()
        
    def close(self):
        self.dialog.destroy()
    

def _simple(dialog_type, header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK,
          default=-1, extra_widgets=None):
    if buttons == Gtk.ButtonsType.OK:
        default = Gtk.ResponseType.OK
    messagedialog = MyDialog(dialog_type, header, sub_header, details,
                         parent=parent, buttons=buttons,
                         default=default, extra_widgets=extra_widgets)
    return messagedialog()

def error(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1, extra_widgets=None):
    return _simple(Gtk.MessageType.ERROR, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default, extra_widgets=extra_widgets)

def info(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1, extra_widgets=None):
    return _simple(Gtk.MessageType.INFO, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default, extra_widgets=extra_widgets)

def warning(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1, extra_widgets=None):
    return _simple(Gtk.MessageType.WARNING, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default, extra_widgets=extra_widgets)

def question(header, sub_header=None, details=None, parent=None, buttons=Gtk.ButtonsType.OK, default=-1, extra_widgets=None):
    return _simple(Gtk.MessageType.QUESTION, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default, extra_widgets=extra_widgets)

def yesno(header, sub_header=None, details=None, parent=None, default=Gtk.ResponseType.YES,
          buttons=Gtk.ButtonsType.YES_NO):
    messagedialog = MyDialog(Gtk.MessageType.WARNING, header, sub_header, details, parent,
                         buttons=buttons, default=default)
    return messagedialog()

def check_folder(directory, parent=None, warn=True):
    if directory is None:
        return False
    if not os.path.exists(directory):
        header = "The folder '%s' does not exist!" % directory
        sub_header = "Please select a valid folder and try again."
        if warn:
            warning(header, sub_header, parent=parent)
        return False
    elif not os.access(directory,os.W_OK):
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
                    buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, _stock,   Gtk.ResponseType.OK))
        if default_folder is None:
            dialog.set_current_folder(config.SESSION_INFO.get('current_path', config.SESSION_INFO['path']))
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
            hbox.pack_start(Gtk.Label ("Format:"), False, False, 0)
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
                

def select_save_file(title, parent=None, formats=[], default_folder=None):
    return select_opensave_file(title, Gtk.FileChooserAction.SAVE, parent=parent, formats=formats, default_folder=default_folder)

def select_open_file(title, parent=None, filters=[], default_folder=None):
    return select_opensave_file(title, Gtk.FileChooserAction.OPEN, parent=parent, filters=filters, default_folder=default_folder)

def select_open_image(parent=None, default_folder=None):
    filters = [
        ('Diffraction Frames', ["*.img", "*.marccd","*.mccd", "*.pck", "*.cbf","*.[0-9][0-9][0-9]", "*.[0-9][0-9][0-9][0-9]" ]),
        ('XDS Spot files', ["SPOT.XDS*", "*.HKL*"] ),
        ('All files', ["*.*"])
    ]
    return select_opensave_file('Select Image', Gtk.FileChooserAction.OPEN, parent=parent, filters=filters, default_folder=default_folder)

class FolderSelector(object):
    def __init__(self, button):
        self.button = button
        self.path = config.SESSION_INFO.get('current_path', config.SESSION_INFO['path'])
        self.label = Gtk.Label(label='')
        self.label.set_alignment(0,0.5)
        self.folders = config.SESSION_INFO.get('directories', [self.path])
        self.icon = Gtk.Image.new_from_stock('gtk-directory', Gtk.IconSize.MENU)
        hbox = Gtk.HBox(False,3)
        hbox.pack_end(self.icon, False, False, 2)
        hbox.pack_start(self.label, True, True, 0)
        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        hbox.show_all()
        self.button.add(hbox)
        self.set_current_folder(self.path)
           
        self.button.connect('button-press-event', self._on_activate)
        self.button.connect('clicked', self._on_activate)
        
        # housekeeping
        self._last_press_button = 1
        self._last_press_time = 0

    def __getattr__(self, key):
        return getattr(self.button, key)
    
    def _create_popup(self):
        # Create Popup menu
        self.menu = Gtk.Menu()
        self.menu_items = []
        for idx, folder in enumerate(self.folders[:min(len(self.folders), 10)]):
            if not os.path.exists(folder): continue
            itm = Gtk.ImageMenuItem(Gtk.STOCK_DIRECTORY)
            name = os.path.relpath(folder, os.environ['HOME'])
            if len(name) > len(folder):
                name = folder
            itm.set_label(name)
            itm.set_always_show_image(True)
            itm.connect("activate", self._on_select_folder, idx)
            itm.show()
            self.menu.append(itm)
            self.menu_items.append(itm)
        sep = Gtk.SeparatorMenuItem()
        sep.show()
        self.menu.append(sep)
        itm = Gtk.MenuItem('Other ...')
        itm.show()
        itm.connect("activate", self._on_select_other)
        self.menu.append(itm)

    def _on_select_folder(self, obj, idx):
        folder = self.folders[idx]
        self.set_current_folder(folder)

    def _on_select_other(self, obj):
        file_open = Gtk.FileChooserDialog(
                        title="Select Folder",
                        parent=self.button.get_toplevel(),
                        action=Gtk.FileChooserAction.SELECT_FOLDER,
                        buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        file_open.set_current_folder(self.path)
        file_open.set_modal(True)
        file_open.connect('response', self._on_dialog_action)
        self.button.set_sensitive(False)
        file_open.show()
        
    def _on_dialog_action(self, dialog, response_id):
        if response_id == Gtk.ResponseType.OK:
            result = dialog.get_filename()
            if result is not None:
                _error_flag = False
                if len(result) > 255:
                    _error_flag = True
                    msg = "The path should be less than 256 characters. Yours '%s' is %d characters long." % (result, len(result))
                elif not re.match('^[\w\-_/]+$', result):
                    _error_flag = True
                    msg = "The path name must be free from spaces and other special characters. Please select another directory."
                else:
                    self.path = result
                    if self.path not in self.folders:
                        self.folders.insert(0, self.path)
                    self.set_current_folder(self.path)
                if _error_flag:
                    warning("Invalid Directory", msg, parent=dialog)
                else:
                    dialog.destroy()
                    self.button.set_sensitive(True)
        else:
            dialog.destroy()
            self.button.set_sensitive(True)
                
    def _on_activate(self, obj, event=None):
        if event is None:
            self.menu.popup(None, None, None, self._last_press_button, self._last_press_time)
        else:
            self._last_press_button = event.button
            self._last_press_time = event.time
                 
    def get_current_folder(self):
        return self.path

    def set_current_folder(self, path):
        if os.path.exists(path):
            self.path = path
        config.SESSION_INFO['current_path'] = self.path
        self._create_popup()
        self.label.set_text(self.path)
        self.label.set_ellipsize(Pango.EllipsizeMode.START)
 

class FolderSelectorButton(Gtk.Button):
    def __init__(self):
        super(FolderSelectorButton, self).__init__()
        self.selector = FolderSelector(self)
    
    def set_current_folder(self, path):
        self.selector.set_current_folder(path)
    
    def get_current_folder(self):
        return self.selector.get_current_folder()
 
