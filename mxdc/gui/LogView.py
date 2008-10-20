import gtk
import gobject
import pango
import time
import logging

class GUIHandler(logging.Handler):
    def __init__(self, view):
        logging.Handler.__init__(self)
        self.view = view
    
    def emit(self, record):
        self.view.log(self.format(record), show_time=False)


class LogView(gtk.Expander):
    def __init__(self, label=None, size=5000):
    
        gtk.Expander.__init__(self, label=label)
        self.buffer_size = size
    
        self.text_buffer = gtk.TextBuffer()
        self.view = gtk.TextView(self.text_buffer)
        self.view.set_editable(False)
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER,gtk.POLICY_AUTOMATIC)
        sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        sw.add(self.view)
        pango_font = pango.FontDescription('Monospace 8')
        self.view.modify_font(pango_font)
        self.add(sw)
        self.show_all()
        self.time_tag = self.text_buffer.create_tag(foreground='Blue')
        
    def clear(self):
        self.text_buffer.delete(self.text_buffer.get_start_iter(), self.text_buffer.get_end_iter())
            
    def log(self, text, show_time=True):
        linecount = self.text_buffer.get_line_count()
        if linecount > self.buffer_size:
            start_iter = self.text_buffer.get_start_iter()
            end_iter = self.text_buffer.get_start_iter()
            end_iter.forward_lines(10)
            self.text_buffer.delete(start_iter, end_iter)
        iter = self.text_buffer.get_end_iter()
        if show_time:
            timestr =  time.strftime('%x %X ')
            self.text_buffer.insert_with_tags(iter, timestr, self.time_tag)
            self.text_buffer.insert(iter, "%s\n" % text )
        else:
            self.text_buffer.insert(iter, "%s\n" % ( text ) )
            
        self.view.scroll_to_iter(iter, 0.4, use_align=True, yalign=0.5)
    
        
