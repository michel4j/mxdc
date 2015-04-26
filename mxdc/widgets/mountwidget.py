import os, sys
from gi.repository import Gtk
from gi.repository import GObject
from mxdc.beamline.mx import IBeamline
from twisted.python.components import globalRegistry
from mxdc.utils.log import get_module_logger
from mxdc.engine import auto
from mxdc.utils.decorators import async

from mxdc.widgets.runmanager import RunManager
from mxdc.utils import gui

_logger = get_module_logger(__name__)

(
    MOUNT_ACTION_NONE,
    MOUNT_ACTION_DISMOUNT,
    MOUNT_ACTION_MOUNT,
    MOUNT_ACTION_MANUAL_DISMOUNT,
    MOUNT_ACTION_MANUAL_MOUNT
) = range(5)

class MountWidget(Gtk.Alignment):
    __gsignals__ = {
        'active-sample': (GObject.SignalFlags.RUN_FIRST, None, [GObject.TYPE_PYOBJECT,]),
        'mount-action-progress': (GObject.SignalFlags.RUN_FIRST, None, [GObject.TYPE_PYOBJECT, GObject.TYPE_BOOLEAN]),
    }
    def __init__(self):
        GObject.GObject.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/mount_widget'), 
                                  'mount_widget')
        self.add(self.mount_widget)
        
        self.beamline = globalRegistry.lookup([], IBeamline)
        
        self.automounter = self.beamline.automounter
        self.manualmounter = self.beamline.manualmounter
        
        self.automounter.connect('mounted', lambda x,y: self.update_active_sample())
        self.manualmounter.connect('mounted', lambda x,y: self.update_active_sample())
                
        self.selected_sample = {}
        self.active_sample = {}
        self.sel_mount_action = MOUNT_ACTION_NONE 
        self.sel_mounting = False
        self.mnt_action_btn.connect('clicked', self.execute_mount_action)
        self.update_active_sample()
        self.busy_text = ''
       
    def __getattr__(self, key):
        try:
            return super(MountWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def update_display(self):
        action = "Mount"
        if self.selected_sample:
            if self.selected_sample.get('name') is not None:
                txt = "%s(%s)" % (self.selected_sample['name'], self.selected_sample.get('port',''))
                self.busy_text = 'Mounting %s ...' % self.selected_sample['name']
            if self.selected_sample == self.active_sample:  
                self.busy_text = 'Dismounting %s ...' % self.selected_sample['name']
                action = "Dismount"
            self.mnt_action_btn.set_sensitive(True)
        else:       
            txt = '<i>None</i>'
            self.mnt_action_btn.set_sensitive(False)
        if self.beamline.automounter.is_busy() or not self.beamline.automounter.is_active():
            self.mnt_action_btn.set_sensitive(False)
        self.crystal_lbl.set_markup(txt)
        self.mnt_action_btn.set_label(action)

    def update_selected(self, sample=None):
        if sample:  
            self.selected_sample = sample
        else:       
            self.selected_sample = {}
        self.update_display()
       
    def update_active_sample(self, sample=None): 
        if sample:
            self.active_sample = sample
        else:
            self.active_sample = {}
        self.update_display()
    
    @async  
    def execute_mount_action(self, obj):
        if self.selected_sample:
            if self.selected_sample.get('load_status', 0) == 1: # Sample Loaded
                if self.beamline.automounter.is_mounted(self.selected_sample['port']): # AUTO DISMOUNT
                    self.sel_mounting = True
                    success = auto.auto_dismount_manual(self.beamline, self.selected_sample['port'])
                elif self.beamline.automounter.is_mountable(self.selected_sample['port']): # AUTO MOUNT
                    self.sel_mounting = True
                    success = auto.auto_mount_manual(self.beamline, self.selected_sample['port'])
                else: # NOTHING
                    pass
            else:
                if self.selected_sample == self.active_sample: # MANUAL DISMOUNT
                    self.beamline.manualmounter.dismount(None)
                else: # MANUAL MOUNT
                    self.beamline.manualmounter.mount(self.selected_sample)
                
        if self.sel_mounting or self.beamline.automounter.is_busy() or not self.beamline.automounter.is_active():
            self.mnt_action_btn.set_sensitive(False)
        else:
            self.mnt_action_btn.set_sensitive(True)
            
        self.sel_mounting = False
