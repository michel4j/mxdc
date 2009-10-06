import os
import gtk
import re

_IMAGE_TYPES = {
    gtk.MESSAGE_INFO: gtk.STOCK_DIALOG_INFO,
    gtk.MESSAGE_WARNING : gtk.STOCK_DIALOG_WARNING,
    gtk.MESSAGE_QUESTION : gtk.STOCK_DIALOG_QUESTION,
    gtk.MESSAGE_ERROR : gtk.STOCK_DIALOG_ERROR,
}

IMAGE_FORMAT = ['jpg', 'png']
IMAGE_FORMAT.sort()
IMAGE_FORMAT_DEFAULT  = 'png'

_BUTTON_TYPES = {
    gtk.BUTTONS_NONE: (),
    gtk.BUTTONS_OK: (gtk.STOCK_OK, gtk.RESPONSE_OK,),
    gtk.BUTTONS_CLOSE: (gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE,),
    gtk.BUTTONS_CANCEL: (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,),
    gtk.BUTTONS_YES_NO: (gtk.STOCK_NO, gtk.RESPONSE_NO,
                         gtk.STOCK_YES, gtk.RESPONSE_YES),
    gtk.BUTTONS_OK_CANCEL: (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                            gtk.STOCK_OK, gtk.RESPONSE_OK),
    }
    
class AlertDialog(gtk.Dialog):
    def __init__(self, parent, flags,
                 type=gtk.MESSAGE_INFO, buttons=gtk.BUTTONS_NONE):
        if not type in _IMAGE_TYPES:
            raise TypeError(
                "type must be one of: %s", ', '.join(_IMAGE_TYPES.keys()))
        if not buttons in _BUTTON_TYPES:
            raise TypeError(
                "buttons be one of: %s", ', '.join(_BUTTON_TYPES.keys()))

        gtk.Dialog.__init__(self, '', parent, flags)
        self.set_border_width(5)
        self.set_resizable(False)
        self.set_has_separator(False)
        # Some window managers (ION) displays a default title (???) if
        # the specified one is empty, workaround this by setting it
        # to a single space instead
        self.set_title(" ")
        self.set_skip_taskbar_hint(True)
        self.vbox.set_spacing(14)

        self._primary_label = gtk.Label()
        self._secondary_label = gtk.Label()
        self._image = gtk.image_new_from_stock(_IMAGE_TYPES[type],
                                               gtk.ICON_SIZE_DIALOG)
        self._image.set_alignment(0.5, 0.0)

        self._primary_label.set_use_markup(True)
        for label in (self._primary_label, self._secondary_label):
            label.set_line_wrap(True)
            label.set_selectable(True)
            label.set_alignment(0.0, 0.5)

        hbox = gtk.HBox(False, 12)
        hbox.set_border_width(5)
        hbox.pack_start(self._image, False, False)

        vbox = gtk.VBox(False, 12)
        hbox.pack_start(vbox, False, False)
        vbox.pack_start(self._primary_label, False, False)
        vbox.pack_start(self._secondary_label, False, False)

        self.details_buffer = gtk.TextBuffer()
        self.details_view = gtk.TextView(self.details_buffer)
        self.details_view.set_editable(False)
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER,gtk.POLICY_AUTOMATIC)
        sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        sw.add(self.details_view)
        
        self._expander = gtk.expander_new_with_mnemonic("Show more _details")
        self._expander.set_spacing(6)
        self._expander.add(sw)
        vbox.pack_start(self._expander, False, False)
        self.vbox.pack_start(hbox, False, False)
        hbox.show_all()
        self._expander.hide()
        self.add_buttons(*_BUTTON_TYPES[buttons])
        self.label_vbox = vbox

    def set_primary(self, text):
        self._primary_label.set_markup(
            "<span weight=\"bold\" size=\"larger\">%s</span>" % text)

    def set_secondary(self, text):
        self._secondary_label.set_markup(text)

    def set_details(self, text):
        iter = self.details_buffer.get_end_iter()
        self.details_buffer.insert(iter, text)
        self._expander.show()

def messagedialog(dialog_type, header, sub_header=None, details=None, parent=None,
                  buttons=gtk.BUTTONS_OK, default=-1):
    """Create and show a MessageDialog.

    @param dialog_type: one of constants
      - gtk.MESSAGE_INFO
      - gtk.MESSAGE_WARNING
      - gtk.MESSAGE_QUESTION
      - gtk.MESSAGE_ERROR
    @param header:      A header text to be inserted in the dialog.
    @param sub_header:  A longer description of the message
    @param details:     Further details of message.
    @param parent:      The parent widget of this dialog
    @type parent:       a gtk.Window subclass
    @param buttons:     The button type that the dialog will be display,
      one of the constants:
       - gtk.BUTTONS_NONE
       - gtk.BUTTONS_OK
       - gtk.BUTTONS_CLOSE
       - gtk.BUTTONS_CANCEL
       - gtk.BUTTONS_YES_NO
       - gtk.BUTTONS_OK_CANCEL
      or a tuple or 2-sized tuples representing label and response. If label
      is a stock-id a stock icon will be displayed.
    @param default: optional default response id
    """
    if buttons in (gtk.BUTTONS_NONE, gtk.BUTTONS_OK, gtk.BUTTONS_CLOSE,
                   gtk.BUTTONS_CANCEL, gtk.BUTTONS_YES_NO,
                   gtk.BUTTONS_OK_CANCEL):
        dialog_buttons = buttons
        buttons = []
    else:
        if buttons is not None and type(buttons) != tuple:
            raise TypeError(
                "buttons must be a GtkButtonsTypes constant or a tuple")
        dialog_buttons = gtk.BUTTONS_NONE

    if parent and not isinstance(parent, gtk.Window):
        raise TypeError("parent must be a gtk.Window subclass")

    d = AlertDialog(parent=parent, flags=gtk.DIALOG_MODAL,
                       type=dialog_type, buttons=dialog_buttons)
    if buttons:
        for text, response in buttons:
            d.add_buttons(text, response)

    d.set_primary(header)
    if sub_header:
        d.set_secondary(sub_header)
        
    if details:
        if isinstance(details, gtk.Widget):
            d.set_details_widget(details)
        elif isinstance(details, basestring):
            d.set_details(details)
        else:
            raise TypeError(
                "long must be a gtk.Widget or a string, not %r" % details)

    if default != -1:
        d.set_default_response(default)

    if parent:
        d.set_transient_for(parent)
        d.set_modal(True)

    response = d.run()
    d.destroy()
    return response

def _simple(type, header, sub_header=None, details=None, parent=None, buttons=gtk.BUTTONS_OK,
          default=-1):
    if buttons == gtk.BUTTONS_OK:
        default = gtk.RESPONSE_OK
    return messagedialog(type, header, sub_header, details,
                         parent=parent, buttons=buttons,
                         default=default)

def error(header, sub_header=None, details=None, parent=None, buttons=gtk.BUTTONS_OK, default=-1):
    return _simple(gtk.MESSAGE_ERROR, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default)

def info(header, sub_header=None, details=None, parent=None, buttons=gtk.BUTTONS_OK, default=-1):
    return _simple(gtk.MESSAGE_INFO, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default)

def warning(header, sub_header=None, details=None, parent=None, buttons=gtk.BUTTONS_OK, default=-1):
    return _simple(gtk.MESSAGE_WARNING, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default)

def question(header, sub_header=None, details=None, parent=None, buttons=gtk.BUTTONS_OK, default=-1):
    return _simple(gtk.MESSAGE_QUESTION, header, sub_header, details, parent=parent,
                   buttons=buttons, default=default)

def yesno(header, sub_header=None, details=None, parent=None, default=gtk.RESPONSE_YES,
          buttons=gtk.BUTTONS_YES_NO):
    return messagedialog(gtk.MESSAGE_WARNING, header, sub_header, details, parent,
                         buttons=buttons, default=default)

def check_folder(directory, parent=None, warn=True):
    print directory
    if directory is None:
        return False
    if not os.path.exists(directory):
        header = "The folder '%s' does not exist!" % directory
        sub_header = "Please select a valid folder and try again."
        if warn:
            response = warning(header, sub_header)
        return False
    elif not os.access(directory,os.W_OK):
        header = "The folder %s can not be written to!" % directory
        sub_header = "Please select a valid folder and try again."
        if warn:
            response = warning(header, sub_header)
        return False
    return True
    
class FolderSelector(object):
    def __init__(self, path=None):
        self.set_path(path)
        
    def set_path(self, path):
        if path is None or not os.path.exists(path):
            self.path = os.environ['HOME']
        else:
            self.path = path
            
    def __call__(self,path=None):
        file_open = gtk.FileChooserDialog(title="Select Folder"
            , action=gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
            , buttons=(gtk.STOCK_CANCEL
                , gtk.RESPONSE_CANCEL
                , gtk.STOCK_OPEN
                , gtk.RESPONSE_OK))
        if path: 
            self.path = path
        file_open.set_current_folder (self.path)
        #file_open.set_uri('file:/%s' % self.path)
        result = None
        if file_open.run() == gtk.RESPONSE_OK:
            result = file_open.get_filename()
            self.path = result
        file_open.destroy()    
        return result

class ImageSelector(object):
    def __init__(self, path=None):
        if path is None or not os.path.exists(path):
            self.path = os.environ['HOME']
        else:
            self.path = path
        #self.path = "/data" + os.sep
        self.img_filter = gtk.FileFilter()
        self.img_filter.set_name("Diffraction Frames")
        self.img_filter.add_pattern("*.img")
        self.img_filter.add_pattern("*.marccd")
        self.img_filter.add_pattern("*.mccd")
        self.img_filter.add_pattern("*.pck")
        self.img_filter.add_pattern("*.[0-9][0-9][0-9]")
        self.img_filter.add_pattern("*.[0-9][0-9][0-9][0-9]")
        
        self.spot_filter = gtk.FileFilter()
        self.spot_filter.set_name("XDS SPOT Files")
        self.spot_filter.add_pattern("SPOT.XDS*")
    
    def set_path(self, path):
        if path is None or not os.path.exists(path):
            self.path = os.environ['HOME']
        else:
            self.path = path
        
    
    def __call__(self,path=None):
        file_open = gtk.FileChooserDialog(title="Select Image"
                , action=gtk.FILE_CHOOSER_ACTION_OPEN
                , buttons=(gtk.STOCK_CANCEL
                            , gtk.RESPONSE_CANCEL
                            , gtk.STOCK_OPEN
                            , gtk.RESPONSE_OK))
   
        file_open.add_filter(self.img_filter)
        file_open.add_filter(self.spot_filter)
        if path: 
            self.path = path
        file_open.set_current_folder (self.path)

        result = (None, None)
        if file_open.run() == gtk.RESPONSE_OK:
            result = (file_open.get_filter(), file_open.get_filename())
            self.path = os.path.dirname(result[1])
        file_open.destroy()   
        return result

class FileSelector(object):
    path = os.environ['HOME']
    
    def __init__(self, title, action, filters):
        self.set_path(os.environ['HOME'])
        if action == gtk.FILE_CHOOSER_ACTION_OPEN:
            resp_stock = gtk.STOCK_OPEN        
        else:
            resp_stock = gtk.STOCK_SAVE
        self.file_open = gtk.FileChooserDialog(title=title, 
                action=action,
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                         resp_stock,   gtk.RESPONSE_OK))
        for name, patterns in filters:
            fil = gtk.FileFilter()
            fil.set_name(name)
            for pat in patterns:
                fil.add_pattern(pat)
            self.file_open.add_filter(fil)
            self.file_open.set_current_folder(self.path)
        self.file_open.set_do_overwrite_confirmation(True)    

    def set_path(self, path):
        if path is None or not os.path.exists(path):
           self.__class__.path = os.environ['HOME'] 
        else:
            self.__class__.path = os.path.dirname(self.filename)
            
    def run(self):
        if self.file_open.run() == gtk.RESPONSE_OK:
            self.filename = self.file_open.get_filename()
            self.filter = self.file_open.get_filter()
            self.set_path(os.path.dirname(self.filename))
        else:
            self.filename = None
            self.filter = None
        self.file_open.destroy()
        return self.filename
    
    def get_filename(self):
        return self.filename
    
    def get_filter(self):
        return self.filter


class FileChooserDialog(gtk.FileChooserDialog):
    def __init__ (self,
                  title   = 'Save Image',
                  parent  = None,
                  action  = gtk.FILE_CHOOSER_ACTION_SAVE,
                  buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                             gtk.STOCK_SAVE,   gtk.RESPONSE_OK),
                  path    = None,
                  ):
        super (FileChooserDialog, self).__init__ (title, parent, action,
                                                  buttons)
        self.set_default_response (gtk.RESPONSE_OK)
        if path: self.path = path
        else:    
            self.path = os.environ['HOME']
            #self.path = "/data" + os.sep
        # create an extra widget to list supported image formats
        self.set_current_folder (self.path)
        self.set_current_name ('image.' + IMAGE_FORMAT_DEFAULT)
        hbox = gtk.HBox (spacing=10)
        hbox.pack_start (gtk.Label ("Image Format:"), expand=False)

        self.cbox = gtk.combo_box_new_text()
        hbox.pack_start (self.cbox)

        for item in IMAGE_FORMAT:
            self.cbox.append_text (item)
        self.cbox.set_active (IMAGE_FORMAT.index (IMAGE_FORMAT_DEFAULT))

        def cb_cbox_changed (cbox, data=None):
            """File extension changed"""
            head, filename = os.path.split(self.get_filename())
            root, ext = os.path.splitext(filename)
            ext = ext[1:]
            new_ext = IMAGE_FORMAT[cbox.get_active()]

            if ext in IMAGE_FORMAT:
                filename = filename.replace(ext, new_ext)
            elif ext == '':
                filename = filename.rstrip('.') + '.' + new_ext

            self.set_current_name (filename)
        self.cbox.connect ("changed", cb_cbox_changed)

        hbox.show_all()
        self.set_extra_widget(hbox)


    def __call__(self):
        while True:
            filename = None
            if self.run() != gtk.RESPONSE_OK:
                break
            filename = self.get_filename()
            menu_ext  = IMAGE_FORMAT[self.cbox.get_active()]
            root, ext = os.path.splitext (filename)
            ext = ext[1:]
            if ext == '':
                ext = menu_ext
                filename += '.' + ext

            if ext in IMAGE_FORMAT:
                self.path = filename
                break
            else:
                error_msg_gtk ('Image format "%s" is not supported' % ext,
                                parent=self)
                self.set_current_name (os.path.split(root)[1] + '.' +
                                        menu_ext)

        self.hide()
        return filename

class DirectoryButton(gtk.Button):
    def __init__(self):
        gtk.Button.__init__(self)
        self.dir_label = gtk.Label(os.environ['HOME'])
        self.dir_label.set_alignment(0,0.5)
        self.icon = gtk.image_new_from_stock('gtk-directory', gtk.ICON_SIZE_MENU)
        hbox = gtk.HBox(False,3)
        hbox.pack_start(self.icon, expand=False, fill=False)
        hbox.pack_start(self.dir_label, expand=True, fill=True)
        hbox.pack_start(gtk.VSeparator(), expand=False, fill=False)
        hbox.pack_end(gtk.Label('...'), expand=False, fill=False)
        hbox.show_all()
        self.add(hbox)
        self.path = os.environ['HOME']
        self.connect('clicked', self.on_select_dir)
        self.tooltips = gtk.Tooltips()
        self.tooltips.enable()

    def on_select_dir(self, widget):
        directory = select_folder(self.path)
        if directory:
            if len(directory) > 255:
                msg1 = "Directory path too long!"
                msg2 = "The path should be less than 256 characters. Yours '%s' is %d characters long. Please use shorter names, and/or fewer levels of subdirectories." % (directory, len(directory))
                result = warning(msg1, msg2)
                self.set_filenamet(self.path)
            elif not re.compile('^[\w/]+$').match(directory):
                msg1 = "Directory name has special characters!"
                msg2 = "The path name must be free from spaces and other special characters. Please select another directory."
                result = warning(msg1, msg2)
                self.set_filename(self.path)
            else:
                self.set_filename(directory)
                return True

        return True
        
    def ellipsize(self,text):
        maxlen = 15
        l = maxlen/2 - 2
        r = maxlen/2 - 1
        if len(text) < maxlen:
            return text
        else:
            return text[:l] + '...' + text[-r:]
        

    def set_filename(self,text):
        self.path = text
        self.tooltips.set_tip(self.dir_label, text)
        dir_txt = os.path.basename(self.path)
        self.dir_label.set_text(self.ellipsize(dir_txt))

    def get_filename(self):
        text = self.path
        if text == '(None)':
            return None
        else:
            return text
    
select_folder = FolderSelector(os.getcwd())
select_image = ImageSelector(os.getcwd())
save_selector = FileChooserDialog()
ImageSelector = None
FolderSelector = None
