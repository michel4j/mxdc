'''
Created on Jan 19, 2010

@author: michel
'''

import os
import gtk
import gtk.glade
import gobject
from twisted.python.components import globalRegistry
from bcm.device import diagnostics

MSG_COLORS = {
    diagnostics.DIAG_STATUS_BAD: '#9a2b2b',
    diagnostics.DIAG_STATUS_WARN: '#8a8241',
    diagnostics.DIAG_STATUS_GOOD: '#396b3b',
    diagnostics.DIAG_STATUS_UNKNOWN: '#2d6294',
}

class DiagnosticDisplay(gtk.Frame):
    def __init__(self, diag):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/diagnostics.glade'), 
                                  'status_widget')
        self._diagnostic = diag
        self.label.set_markup("<span color='#444647'><b>%s</b></span>" % self._diagnostic.description)
        self._diagnostic.connect('status', self.on_status_changed)
        self._status = diagnostics.DIAG_STATUS_UNKNOWN
        self.add(self.status_widget)
        self.show_all()
        
    def __getattr__(self, key):
        try:
            return super(DiagnosticDisplay).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def on_status_changed(self, obj, data):
        if data['status'] == self._status:
            return 
        # Set Icon
        if data['status'] == diagnostics.DIAG_STATUS_BAD:
            self.icon.set_from_stock('gtk-dialog-error', gtk.ICON_SIZE_MENU)
        elif data['status'] == diagnostics.DIAG_STATUS_GOOD:
            self.icon.set_from_stock('gtk-apply', gtk.ICON_SIZE_MENU)
        elif data['status'] == diagnostics.DIAG_STATUS_WARN:
            self.icon.set_from_stock('gtk-dialog-warning', gtk.ICON_SIZE_MENU)
        else:
            self.icon.set_from_stock('gtk-dialog-question', gtk.ICON_SIZE_MENU)
        
        self.info.set_markup('<span color="%s"><i>%s</i></span>' % (MSG_COLORS[data['status']], data['message']))
        self._status = data['status']
        
        

class DiagnosticsViewer(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self, False, 3)
        self._num = 0
        #fetch and add diagnostics
        _dl = globalRegistry.subscriptions([], diagnostics.IDiagnostic)
        for diag in _dl:
            self.add_diagnostic(diag)
        self.set_border_width(36)
        self.pack_end(gtk.Label(''), expand=True, fill=True)
        self.show_all()
        


    def add_diagnostic(self, diag):
        if self._num > 0:
            hs = gtk.HSeparator()
            hs.set_sensitive(False)
            self.pack_start(hs, expand=False, fill=False)
        self.pack_start(DiagnosticDisplay(diag), expand=False, fill=False)
        self._num += 1
        