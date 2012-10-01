# -*- coding: utf-8 -*-
import gtk, gobject
import sys, os, time
import pango

from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.misc import ActiveLabel, TextStatusDisplay, ShutterButton, StatusBox

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
        
        options = {
            'xoptions' : gtk.EXPAND|gtk.FILL,
            }
        self.layout_table.attach(self._frame_control('Beamline', gtk.Label(beamline.name), gtk.SHADOW_IN), 8, 9 , 0, 1, **options)
        pango_font = pango.FontDescription('Monospace 9')
        
        beamline.ring_current.units = 'mA'
        self.cur = ActiveLabel(beamline.ring_current, format="%+0.1f")
        self.layout_table.attach(self._frame_control('Ring', self.cur, gtk.SHADOW_IN), 7, 8 , 0, 1, **options)
        
        self.i2 = ActiveLabel(beamline.i_2.value, format="%+0.2e")
        self.layout_table.attach(self._frame_control('I2', self.i2, gtk.SHADOW_IN), 6, 7 , 0, 1, **options)
        
        self.i1 = ActiveLabel(beamline.i_1.value, format="%+0.2e")
        self.layout_table.attach(self._frame_control('I1', self.i1, gtk.SHADOW_IN), 5, 6 , 0, 1, **options)
        
        self.i0 = ActiveLabel(beamline.i_0.value, format="%+0.2e")
        self.layout_table.attach(self._frame_control('I0', self.i0, gtk.SHADOW_IN), 4, 5 , 0, 1, **options)
        
        _cmap = {True:'green',  False:'red'}
        _vmap = {True:'OPEN',  False:'CLOSED'}
        self.sh_stat = StatusBox(beamline.registry['exposure_shutter'], color_map=_cmap, value_map=_vmap)
        self.layout_table.attach(self._frame_control('Shutter', self.sh_stat, gtk.SHADOW_IN), 3, 4 , 0, 1, **options)
      

        _cmap = {'MOUNTING':'blue',
            'CENTERING':'orange',
            'SCANNING':'green',
            'COLLECT': 'green',
            'BEAM': 'red',
            'MOVING': 'gray',
            'INIT':'gray',
            'ALIGN': 'gray',
            }

        self.gonio_mode = StatusBox(beamline.goniometer, signal='mode', color_map=_cmap)
        self.layout_table.attach(self._frame_control('Mode', self.gonio_mode, gtk.SHADOW_IN), 2, 3 , 0, 1, **options)
        #self.progress_bar = gtk.ProgressBar()
        #self.progress_bar.set_size_request(50,-1)
        #self.layout_table.attach(self.progress_bar, 2, 3, 0, 1, xoptions=gtk.FILL|gtk.EXPAND)
        
        hseparator = gtk.HSeparator()
        hseparator.set_size_request(-1,3)
        #self.pack_start(hseparator, expand= False, fill=False, padding=0)
        frame = self.get_children()[0]
        label = frame.get_children()[0]
        frame.remove(label)
        
        self.layout_table.attach(self._frame_control(None, label, gtk.SHADOW_NONE), 0,2,0,1, **options)
        frame.add(self.layout_table)

        for lbl in [self.cur, self.i2, self.i1, self.i0]:
            lbl.modify_font(pango_font)

        self.show_all()    
    
    def _update_mode(self, obj, val):
        self.gonio_mode.set_markup(val)
        
    def _frame_control(self, label, widget, shadow):
        hbox = gtk.HBox(False, 2)
        hbox.pack_end(widget, expand=True, fill=True)
        if label is not None:
            descr = gtk.Label('<i><span color="#333333">%s:</span></i>' % label)
            descr.set_sensitive(False)
            descr.set_use_markup(True)
            hbox.pack_start(gtk.VSeparator(), expand=False, fill=True)
            hbox.pack_start(descr, expand=False, fill=True)
        #frame = gtk.Frame()
        #frame.set_shadow_type(shadow)
        #frame.add(hbox)
        return hbox
            
