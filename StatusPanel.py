#!/usr/bin/env python
import gtk, gobject
import sys, os, time

from Beamline import beamline
from ActiveWidgets import *

class StatusPanel(gtk.VBox):
	def __init__(self):
		gtk.VBox.__init__(self,False,0)
		self.layout_table = gtk.Table(1,10,True)
		self.layout_table.set_col_spacings(4)
		self.layout_table.set_border_width(1)
		
		self.clock = gtk.Label()						
		self.layout_table.attach(self.__frame_control('',self.clock, gtk.SHADOW_ETCHED_IN), 10, 11 , 0, 1)

		self.intensity = DiagnosticLabel(beamline['detectors']['current'], format="%5.1f")
		self.layout_table.attach(self.__frame_control('Cur<sub>mA</sub>', self.intensity, gtk.SHADOW_IN), 9, 10 , 0, 1)
		
		self.intensity = DiagnosticLabel(beamline['detectors']['i1_bpm'], format="%8.4g")
		self.layout_table.attach(self.__frame_control('I1<sub>A</sub>', self.intensity, gtk.SHADOW_IN), 8, 9 , 0, 1)
		
		self.intensity = DiagnosticLabel(beamline['detectors']['i0_bpm'], format="%8.4g")
		self.layout_table.attach(self.__frame_control('I0<sub>A</sub>', self.intensity, gtk.SHADOW_IN), 7, 8 , 0, 1)
		
		gobject.timeout_add(500,self.update_clock)
		hseparator = gtk.HSeparator()
		hseparator.set_size_request(-1,3)
		self.pack_start(hseparator, expand= False, fill=False, padding=0)
		self.pack_end(self.layout_table, expand= False, fill=False, padding=0)
		self.show_all()	
	
	def __frame_control(self, label, widget, shadow):
		assert( shadow in [gtk.SHADOW_ETCHED_IN, gtk.SHADOW_ETCHED_OUT, gtk.SHADOW_IN, gtk.SHADOW_OUT ] )
		frame = gtk.Frame()
		frame.set_shadow_type(shadow)
		frame.add(widget)
		descr = gtk.Label("<small>%s</small>" % label)
		descr.set_use_markup(True)
		hbox = gtk.HBox(False,3)
		hbox.pack_start(descr, expand=False, fill=False)
		hbox.pack_end(frame, expand=True, fill=True)
		return hbox

	def update_clock(self):
		timevals = time.localtime()
		time_string = "%02d:%02d:%02d" % timevals[3:6]
		self.clock.set_text(time_string)
		return True
		
if __name__ == "__main__":
   
	win = gtk.Window()
	win.connect("destroy", lambda x: gtk.main_quit())
	#win.set_default_size(300,400)
	win.set_title("CollectManager Widget Demo")

	example = StatusPanel()
	win.add(example)
	win.show_all()

	try:
		gtk.main()
	except KeyboardInterrupt:
		print "Quiting..."
		sys.exit()
		
