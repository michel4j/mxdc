'''
Created on Jan 19, 2010

@author: michel
'''

import os
import gtk
import gtk.glade
import gobject

class DiagnosticDisplay(gtk.Frame):
    def __init__(self, diag):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/diagnostics.glade'), 
                                  'status_widget')
        self._diagnostic = diag
        self._diagnostic.connect('status', self.on_status_changed)
        
    def __getattr__(self, key):
        try:
            return super(DiagnosticDisplay).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def on_status_changed(self, obj, data):
        # Set Icon
        # Set comments
        # Set Tooltip
        pass
        

class DiagnosticsViewer(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self, True, 3)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/diagnostics.glade'), 
                                  'window1')
        self.diagnostics = []
        self.show_all()


    def add_diagnostic(self, diag):
        self.pack_start(DiagnosticDisplay(diag), expand=False, fill=False)
        