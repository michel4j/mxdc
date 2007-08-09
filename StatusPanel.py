#!/usr/bin/env python
import gtk, gobject
import sys, os, time


class StatusPanel(gtk.VBox):
	def __init__(self):
		gtk.VBox.__init__(self,False,0)
		self.layout_table = gtk.Table(1,5,True)
		self.layout_table.set_col_spacings(4)
		self.layout_table.set_border_width(1)
		
		#    key       txt        pos frame? alignment
		items = {
			'status': ('IDLE',    	0, 	1,	0.5),
			'label1': ('Hutch:',  	1, 	0,	1),
			'hutch':  ('OPEN',    	2, 	1,	0.5),
			'label2': ('Energy:', 	3,	0,	1),
			'energy': ('12.6580', 	4, 	1,	0.5),
			'label3': ('keV',		5, 	0,	0),
			'label5': ('I<sub>0</sub>:', 6, 0, 1),
			'flux':	  ('6.00 e-6',	7,	1,	0.5), 
			'label4': ('Shutter',	8,	0,  1),
			'shutter': ('OPEN',		9,	1,	0.5),
			'clock':  ('14:43:17',	10, 	1,	0.5)	
		}
		self.controls = {}
		for key in items.keys():
			val = items[key]
			self.controls[key] = gtk.Label(val[0])
			self.controls[key].set_alignment(val[3], 0.5)
			self.controls[key].set_use_markup(True)
							
			if val[2] == 1:
				self.layout_table.attach(self.__frame_control(self.controls[key], gtk.SHADOW_IN), val[1], val[1]+1 , 0, 1)
			else:
				self.layout_table.attach(self.controls[key], val[1], val[1]+1 , 0, 1)
		
		gobject.timeout_add(500,self.update_clock)
		hseparator = gtk.HSeparator()
		hseparator.set_size_request(-1,3)
		self.pack_start(hseparator, expand= False, fill=False, padding=0)
		self.pack_end(self.layout_table, expand= False, fill=False, padding=0)
		self.show_all()	
	
	def __frame_control(self, widget, shadow):
		assert( shadow in [gtk.SHADOW_ETCHED_IN, gtk.SHADOW_ETCHED_OUT, gtk.SHADOW_IN, gtk.SHADOW_OUT ] )
		frame = gtk.Frame()
		frame.set_shadow_type(shadow)
		frame.add(widget)
		return frame

	def update_clock(self):
		timevals = time.localtime()
		time_string = "%02d:%02d:%02d" % timevals[3:6]
		self.controls['clock'].set_text(time_string)
		return True

	def update_values(self,dict):		
		for key in dict.keys():
			self.controls[key].set_text(dict[key])
		
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
		
