from gi.repository import Gtk
from gi.repository import GObject
from gi.repository import Pango
import time
import logging
import re

class GUIHandler(logging.Handler):
    def __init__(self, viewer):
        logging.Handler.__init__(self)
        self.viewer = viewer
    
    def emit(self, record):
        GObject.idle_add(self.viewer.add_text, self.format(record), True)

class TextViewer(object):
    def __init__(self, view, size=5000, font='Monospace 8'):  
        self.buffer_size = size    
        self.view = view
        self.text_buffer = self.view.get_buffer()
        self.view.set_editable(False)
        pango_font = Pango.FontDescription(font)
        self.view.modify_font(pango_font)
        self.wrap_mode = Gtk.WrapMode.WORD
        self.prefix = ''
        color_chart = {'INFO': 'Blue',
               'ERROR': 'Red',
               'DEBUG': 'Gray',
               'CRITICAL': 'Red',
               'WARNING': 'Purple',
               'DEFAULT': 'Black',
               }
        self.tags = {}
        for key,v in color_chart.items():
            self.tags[key] = self.text_buffer.create_tag(foreground=v)
            
    def set_prefix(self, txt):
        self.prefix = txt
        
    def clear(self):
        self.text_buffer.delete(self.text_buffer.get_start_iter(), self.text_buffer.get_end_iter())
            
    def add_text(self, text, log=False):
        linecount = self.text_buffer.get_line_count()
        if linecount > self.buffer_size:
            start_iter = self.text_buffer.get_start_iter()
            end_iter = self.text_buffer.get_start_iter()
            end_iter.forward_lines(10)
            self.text_buffer.delete(start_iter, end_iter)
        _iter = self.text_buffer.get_end_iter()
        if log:
            tag = self.tags['DEFAULT']
            for key in ['INFO', 'DEBUG', 'ERROR', 'WARNING', 'CRITICAL']:
                if re.search(key, text):
                    tag = self.tags[key]
            self.text_buffer.insert_with_tags(_iter, "%s%s\n" % (self.prefix, text), tag)
        else:
            self.text_buffer.insert(_iter, "%s%s\n" % (self.prefix, text) )         
        _iter = self.text_buffer.get_end_iter()
        self.view.scroll_to_iter(_iter, 0, True, 0.5, 0.5)
    
        
