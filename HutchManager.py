#!/usr/bin/env python
import gtk, gobject
import sys, os
from Predictor import Predictor
from SampleViewer import SampleViewer
from HutchViewer import HutchViewer
from LogView import LogView
from ActiveWidgets import *
from Beamline import beamline
from Scripting import Script
from Scripts import prepare_for_mounting, restore_beamstop


(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

script_data = [
    ('optimize_mono_slits', 'Optimize Monochromator slits',False),
    ('optimize_exposure_box', 'Optimize Exposure-Box',False),
    ('optimize_beam_stop', 'Optimize Beam-stop',False),
    ('calibrate_robot', 'Calibrate the Robot',False),
    ('optimize_after_energy_change', 'Optimize Mono Pitch',False)
]

class HutchManager(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)
        hbox1 = gtk.HBox(False,0)
        hbox2 = gtk.HBox(False,6)
        hbox3 = gtk.HBox(False,6)
        self.predictor = Predictor()

        self.predictor.set_size_request(300,300)
        self.show_all()

        videobook = gtk.Notebook()
        video_size = 0.7
        self.sample_viewer = SampleViewer(video_size)
        self.hutch_viewer = HutchViewer(video_size)
        videobook.insert_page( self.sample_viewer, tab_label=gtk.Label('Sample Camera') )
        videobook.insert_page( self.hutch_viewer, tab_label=gtk.Label('Hutch Camera') )
        
        self.entry = {
            'energy':       ActiveEntry('Energy', positioner=beamline['motors']['energy'], format="%0.4f"),
            'attenuation':  ActiveEntry('Attenuation', positioner=beamline['attenuator'], format="%0.2g"),
            'angle':        ActiveEntry('Omega', positioner=beamline['motors']['omega'], format="%0.3f"),
            'beam_width':   ActiveEntry('Beam width', positioner=beamline['motors']['gslits_hgap'], format="%0.3f"),
            'beam_height':  ActiveEntry('Beam height', positioner=beamline['motors']['gslits_vgap'], format="%0.3f"),
            'distance':     ActiveEntry('Detector Distance', positioner=beamline['motors']['detector_dist'], format="%0.2f"),
            'beam_stop':    ActiveEntry('Beam-stop', positioner=beamline['motors']['bst_z'], format="%0.2f"),
            'two_theta':    ActiveEntry('Detector TwoTheta',positioner=beamline['motors']['detector_2th'], format="%0.2f")
        }
        beamline['motors']['detector_dist'].connect('changed', self.predictor.on_distance_changed)
        beamline['motors']['detector_2th'].connect('changed', self.predictor.on_two_theta_changed)
        beamline['motors']['energy'].connect('changed', self.predictor.on_energy_changed)
        
        self.predictor.set_energy( self.entry['energy'].get_position() )        
        self.predictor.set_distance( self.entry['distance'].get_position() )
        self.predictor.update(force=True)
        
               

        motor_vbox1 = gtk.VBox(False,0)
        for key in ['energy','attenuation','beam_width','beam_height']:
            motor_vbox1.pack_start(self.entry[key], expand=True, fill=False)

        motor_vbox2 = gtk.VBox(False,0)        
        for key in ['angle','beam_stop','distance','two_theta']:
            motor_vbox2.pack_start(self.entry[key], expand=True, fill=False)
        
        self.device_box = gtk.HBox(True,6)
           
        diagram = gtk.Image()
        diag_frame = gtk.Frame()
        diag_frame.set_shadow_type(gtk.SHADOW_IN)
        diag_frame.set_border_width(6)
        diag_frame.add(diagram)
        diagram.set_from_file(sys.path[0] + '/images/hutch_devices.png')
        
        control_box = gtk.VButtonBox()
        control_box.set_border_width(6)
        self.front_end_btn = ShutterButton(beamline['shutters']['psh1'], 'Front End Shutter')
        self.shutter_btn = ShutterButton(beamline['shutters']['xbox_shutter'], 'Exp.Box Shutter')
        self.optimize_btn = gtk.Button('Optimize Beam')
        self.mount_btn = gtk.Button('Prepare for Mounting')
        self.mount_btn.connect('clicked',self.prepare_mounting)
        self.reset_btn = gtk.Button('Reset Beamstop')
        self.reset_btn.connect('clicked',self.restore_beamstop)
        self.front_end_btn.set_sensitive(False)
        self.optimize_btn.set_sensitive(False)
        control_box.pack_start(self.front_end_btn)
        control_box.pack_start(self.shutter_btn)
        control_box.pack_start(self.optimize_btn)
        control_box.pack_start(self.mount_btn)
        control_box.pack_start(self.reset_btn)
        
        hbox1.pack_start(control_box, expand=False, fill=False)
        hbox1.pack_end(diag_frame, expand=False, fill=True)
        self.device_box.pack_start(motor_vbox1,expand=False,fill=True)
        self.device_box.pack_start(motor_vbox2,expand=False,fill=True)
        
        hbox1.pack_end(self.device_box,expand=False,fill=True)
        
        self.pack_start(hbox1)
        hbox3.pack_start(videobook, expand=False,fill=False)
        hbox3.set_border_width(6)
        predictor_frame = gtk.Notebook()
        pred_align = gtk.Alignment(0.5,0.5, 0, 0)
        pred_align.add(self.predictor)
        pred_align.set_border_width(6)
        predictor_frame.insert_page(pred_align,tab_label=gtk.Label('Resolution Predictor'))
        self.predictor.connect('realize',self.update_pred)
        hbox3.pack_start(predictor_frame, expand=True,fill=True)
        
        #automounter = gtk.Notebook()
        junk = gtk.DrawingArea()
        junk.set_size_request(300,300)
        #predictor_frame.insert_page(junk, tab_label=gtk.Label('Sample Auto-mounting'))
        #hbox3.pack_start(automounter)
        self.pack_start(hbox3)

        self.script_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN
        )
        self.script_list = gtk.TreeView(model=self.script_store)
        self.script_list.set_rules_hint(True)
        for item in script_data:
            self.__add_script(item)
        script_vbox = gtk.VBox(False,6)
        script_vbox.set_border_width(6)
        renderer = gtk.CellRendererText()
        renderer.set_data('column',COLUMN_DESCRIPTION)
        column1 = gtk.TreeViewColumn('Scripts', renderer, text=COLUMN_DESCRIPTION)
        
        self.script_list.append_column(column1)
        sw = gtk.ScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add(self.script_list)
        script_vbox.pack_start(sw)
        self.run_script_btn= gtk.Button('Execute Script')
        script_vbox.pack_end(self.run_script_btn,expand=False, fill=False)
        script_vbox.set_sensitive(False)
        #hbox1.pack_end(script_vbox,expand=False, fill=False)
        self.show_all()

    def update_pred(self, widget):
        self.predictor.update()
        return True
        
    def prepare_mounting(self, widget):
        self.device_box.set_sensitive(False)
        script = Script(prepare_for_mounting)
        script.start()

    def restore_beamstop(self, widget):
        script = Script(restore_beamstop)
        script.start()
        script.connect('done', lambda x: self.device_box.set_sensitive(True))

    def stop(self):
        self.sample_viewer.stop()
        self.hutch_viewer.stop()
                
    def __add_script(self, item): 
        iter = self.script_store.append()                
        self.script_store.set(iter, 
            COLUMN_NAME, item[COLUMN_NAME], 
            COLUMN_DESCRIPTION, item[COLUMN_DESCRIPTION],
            COLUMN_AVAILABLE, item[COLUMN_AVAILABLE]
        )
        
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Hutch Demo")
    
    hutch = HutchManager()
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."
        hutch.stop()
        


if __name__ == '__main__':
    main()
