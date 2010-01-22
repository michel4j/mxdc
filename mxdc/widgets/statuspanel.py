# -*- coding: utf-8 -*-
import gtk, gobject
import sys, os, time

from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.misc import ActiveLabel, TextStatusDisplay

class StatusPanel(gtk.Statusbar):
    def __init__(self):
        gtk.Statusbar.__init__(self)
        self.set_has_resize_grip(False)
        self.layout_table = gtk.Table(1, 9, True)
        self.layout_table.set_col_spacings(2)
        self.layout_table.set_border_width(3)

        beamline = globalRegistry.lookup([], IBeamline)      
        if beamline is None:
            return
        self.layout_table.attach(self._frame_control('Beamline', gtk.Label(beamline.name), gtk.SHADOW_IN), 8, 9 , 0, 1)
        
        
        beamline.registry['ring_current'].units = 'mA'
        self.intensity = ActiveLabel(beamline.registry['ring_current'], format="<tt><small>%5.2f</small></tt>")
        self.layout_table.attach(self._frame_control('Ring', self.intensity, gtk.SHADOW_IN), 7, 8 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.registry['i_2'].value, format="<tt><small>%8.2e</small></tt>")
        self.layout_table.attach(self._frame_control('I2', self.intensity, gtk.SHADOW_IN), 6, 7 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.registry['i_1'].value, format="<tt><small>%8.2e</small></tt>")
        self.layout_table.attach(self._frame_control('I1', self.intensity, gtk.SHADOW_IN), 5, 6 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.i_0.value, format="<tt><small>%8.2e</small></tt>")
        self.layout_table.attach(self._frame_control('I0', self.intensity, gtk.SHADOW_IN), 4, 5 , 0, 1)
        
        _map = {True:'<span color="#009900"><small>OPEN</small></span>',
                False:'<span color="#990000"><small>CLOSED</small></span>'}
        self.sh_stat = TextStatusDisplay(beamline.registry['exposure_shutter'], text_map=_map)
        self.layout_table.attach(self._frame_control('Shutter', self.sh_stat, gtk.SHADOW_IN), 3, 4 , 0, 1)
      
        _map = {'MOUNTING':'<span color="#009999"><small>MOUNTING</small></span>',
                'CENTERING':'<span color="#999900"><small>CENTERING</small></span>',
                'COLLECT': '<span color="#009900"><small>COLLECT</small></span>',
                'BEAM': '<span color="#990000"><small>BEAM</small></span>',
                'UNKNOWN': '<span color="#000099"><small>UNKNOWN</small></span>',
                'INIT':'<span color="#000099"><small>INIT</small></span>',
                'ALIGN': '<span color="#000099"><small>ALIGN</small></span>',
                }
        self.gonio_mode = TextStatusDisplay(beamline.registry['goniometer'], sig='mode', text_map=_map)
        self.layout_table.attach(self._frame_control('Mode', self.gonio_mode, gtk.SHADOW_IN), 2, 3 , 0, 1)
        #self.progress_bar = gtk.ProgressBar()
        #self.progress_bar.set_size_request(50,-1)
        #self.layout_table.attach(self.progress_bar, 2, 3, 0, 1, xoptions=gtk.FILL|gtk.EXPAND)
        
        hseparator = gtk.HSeparator()
        hseparator.set_size_request(-1,3)
        #self.pack_start(hseparator, expand= False, fill=False, padding=0)
        frame = self.get_children()[0]
        label = frame.get_children()[0]
        frame.remove(label)
        self.layout_table.attach(self._frame_control(None, label, gtk.SHADOW_IN), 0,3,0,1)
        frame.add(self.layout_table)
        #self.remove(child, None)
        #self.pack_start(self.layout_table, expand= False, fill=False, padding=0)
        self.show_all()    
    
    def _update_mode(self, obj, val):
        self.gonio_mode.set_markup('<small>%s</small>' % val)
        
    def _frame_control(self, label, widget, shadow):
        hbox = gtk.HBox(False,2)
        hbox.pack_end(widget)
        if label is not None:
            descr = gtk.Label('<span color="#333333"><i>%s:</i></span>' % label)
            descr.set_sensitive(False)
            descr.set_use_markup(True)
            hbox.pack_start(gtk.VSeparator(), expand=False, fill=False)
            hbox.pack_start(descr, expand=False, fill=False)
        #frame = gtk.Frame()
        #frame.set_shadow_type(shadow)
        #frame.add(hbox)
        return hbox
            
