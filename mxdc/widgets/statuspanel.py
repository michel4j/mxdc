# -*- coding: utf-8 -*-
import gtk, gobject
import sys, os, time

from mxdc.widgets.misc import ActiveLabel, ShutterStatus

class StatusPanel(gtk.Statusbar):
    def __init__(self, beamline):
        gtk.Statusbar.__init__(self)
        self.set_has_resize_grip(False)
        self.layout_table = gtk.Table(1, 9, True)
        self.layout_table.set_col_spacings(2)
        self.layout_table.set_border_width(1)

        self.layout_table.attach(self._frame_control('Beamline', gtk.Label(beamline.name), gtk.SHADOW_IN), 8, 9 , 0, 1)
        
        self.sh_stat = ShutterStatus(beamline.registry['exposure_shutter'])
        self.layout_table.attach(self._frame_control('Shutter', self.sh_stat, gtk.SHADOW_IN), 6, 7 , 0, 1)
        
        beamline.registry['ring_current'].units = 'mA'
        self.intensity = ActiveLabel(beamline.registry['ring_current'], format="<tt><small>%5.1f</small></tt>")
        self.layout_table.attach(self._frame_control('Ring', self.intensity, gtk.SHADOW_IN), 7, 8 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.registry['i_2'].value, format="<tt><small>%8.1e</small></tt>")
        self.layout_table.attach(self._frame_control('I₂', self.intensity, gtk.SHADOW_IN), 5, 6 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.registry['i_1'].value, format="<tt><small>%8.1e</small></tt>")
        self.layout_table.attach(self._frame_control('I₁', self.intensity, gtk.SHADOW_IN), 4, 5 , 0, 1)
        
        self.intensity = ActiveLabel(beamline.i_0.value, format="<tt><small>%8.1e</small></tt>")
        self.layout_table.attach(self._frame_control('I₀', self.intensity, gtk.SHADOW_IN), 3, 4 , 0, 1)
        
        #self.progress_bar = gtk.ProgressBar()
       # self.progress_bar.set_size_request(50,-1)
        #self.layout_table.attach(self.progress_bar, 2, 3, 0, 1, xoptions=gtk.FILL|gtk.EXPAND)
        
        hseparator = gtk.HSeparator()
        hseparator.set_size_request(-1,3)
        #self.pack_start(hseparator, expand= False, fill=False, padding=0)
        frame = self.get_children()[0]
        label = frame.get_children()[0]
        frame.remove(label)
        self.layout_table.attach(self._frame_control(None,label, gtk.SHADOW_IN), 0,3,0,1)
        frame.add(self.layout_table)
        #self.remove(child, None)
        #self.pack_start(self.layout_table, expand= False, fill=False, padding=0)
        self.show_all()    
    
    def _frame_control(self, label, widget, shadow):
        hbox = gtk.HBox(False,2)
        hbox.pack_end(widget, expand=True, fill=True)
        if label is not None:
            descr = gtk.Label('<b>%s:</b>' % label)
            descr.set_use_markup(True)
            hbox.pack_start(gtk.VSeparator())
            hbox.pack_start(descr)
        #frame = gtk.Frame()
        #frame.set_shadow_type(shadow)
        #frame.add(hbox)
        return hbox
    
    def update_clock(self):
        timevals = time.localtime()
        time_string = "%02d:%02d:%02d" % timevals[3:6]
        self.clock.set_text(time_string)
        return True
        