import gtk
import gobject
import pango
import time
import logging
import re

class GUIHandler(logging.Handler):
    def __init__(self, viewer):
        logging.Handler.__init__(self)
        self.viewer = viewer
    
    def emit(self, record):
        self.viewer.add_text(self.format(record), log=True)


class TextViewer(object):
    def __init__(self, view, size=5000):  
        self.buffer_size = size    
        self.view = view
        self.text_buffer = self.view.get_buffer()
        self.view.set_editable(False)
        pango_font = pango.FontDescription('Monospace 8')
        self.view.modify_font(pango_font)
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
            

        
    def clear(self):
        self.text_buffer.delete(self.text_buffer.get_start_iter(), self.text_buffer.get_end_iter())
            
    def add_text(self, text, log=False):
        linecount = self.text_buffer.get_line_count()
        if linecount > self.buffer_size:
            start_iter = self.text_buffer.get_start_iter()
            end_iter = self.text_buffer.get_start_iter()
            end_iter.forward_lines(10)
            self.text_buffer.delete(start_iter, end_iter)
        iter = self.text_buffer.get_end_iter()
        if log:
            tag = self.tags['DEFAULT']
            for key in ['INFO', 'DEBUG', 'ERROR', 'WARNING', 'CRITICAL']:
                if re.search(key, text):
                    tag = self.tags[key]
            self.text_buffer.insert_with_tags(iter, "%s\n" % (text), tag)
        else:
            self.text_buffer.insert(iter, "%s\n" % (text) )         
        self.view.scroll_to_iter(iter, 0.4, use_align=True, yalign=0.5)
    
        
