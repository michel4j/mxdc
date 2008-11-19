import gtk, gobject
import sys, os
from Predictor import Predictor
from SampleViewer import SampleViewer
from HutchViewer import HutchViewer
from SamplePicker import SamplePicker
from LogView import LogView
from ActiveWidgets import *
from bcm.tools.scripting import Script
from bcm.scripts.misc import prepare_for_mounting, restore_beamstop

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

class SampleManager(gtk.HBox):
    def __init__(self, beamline):
        gtk.HBox.__init__(self)
        vbox1 = gtk.VBox(False,0)
        vbox2 = gtk.VBox(False,6)
        vbox3 = gtk.VBox(False,6)
        self.beamline = beamline

        videobook = gtk.Notebook()
        video_size = 0.7
        self.sample_viewer = SampleViewer(self.beamline)
        self.hutch_viewer = HutchViewer(self.beamline)
        videobook.insert_page( self.sample_viewer, tab_label=gtk.Label('Sample Camera') )
        videobook.insert_page( self.hutch_viewer, tab_label=gtk.Label('Hutch Camera') )
        
        self.entry = {
            'beam_width':   MotorEntry(self.beamline.beam_w, 'Beam width', format="%0.3f"),
            'beam_height':  MotorEntry(self.beamline.beam_h, 'Beam height', format="%0.3f"),
        }        

        motor_box = gtk.VBox(False,0)
        for key in ['beam_width','beam_height']:
            motor_box.pack_start(self.entry[key], expand=True, fill=False)
        _hbox = gtk.HBox(False, 6)
        cryo = CryojetWidget(self.beamline.cryojet)
        _hbox.pack_start(motor_box, expand=False, fill=True)
        _hbox.pack_start(cryo, expand=False, fill=True)
        vbox3.pack_start(_hbox, expand=False, fill=True)
        
        vbox3.pack_end(videobook, expand=False,fill=False)
        vbox3.set_border_width(6)
        tool_book = gtk.Notebook()
        self.sample_picker = SamplePicker()
        self.sample_picker.set_border_width(6)
        tool_book.insert_page(self.sample_picker, tab_label=gtk.Label('Automatic Sample Mounting'))
        vbox1.pack_end(tool_book, expand=False,fill=False)
        
        self.pack_start(vbox1, expand=False, fill=False)
        self.pack_start(vbox2, expand=False, fill=False)
        self.pack_start(vbox3, expand=False, fill=False)
        self.show_all()

    def update_pred(self, widget):
        self.predictor.update()
        return True
        
    def prepare_mounting(self, widget):
        self.device_box.set_sensitive(False)
        script = Script(prepare_for_mounting, self.beamline)
        script.start()

    def restore_beamstop(self, widget):
        script = Script(restore_beamstop, self.beamline)
        script.start()
        script.connect('done', lambda x: self.device_box.set_sensitive(True))

    def stop(self):
        self.sample_viewer.stop()
        self.hutch_viewer.stop()
                        
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Hutch Demo")
    
    hutch = SampleManager()
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."
        hutch.stop()

if __name__ == '__main__':
    main()
