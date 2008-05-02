import gtk, gobject
import os, sys, time

class PositionerEntry(gtk.Frame):
    def __init__( self, positioner, label="",  format="%g",  width=8):
        gtk.Frame.__init__(self, label)

        # create gui layout
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.value_box = gtk.Label()
        self.value_box.set_alignment(1, 0.5)
        self.entry_box = gtk.Entry()
        self.entry_box.set_has_frame(False)
        self.entry_box.set_width_chars(width)
        self.entry_box.set_alignment(1)
        self.act_btn = gtk.Button()
        self.undo_btn =  gtk.Button()
        self.act_btn.add(gtk.image_new_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU))
        self.undo_btn.add(gtk.image_new_from_stock('gtk-undo',gtk.ICON_SIZE_MENU))
        self.undo_btn.set_sensitive(False)
        self.hbox1 = gtk.HBox(False,2)
        self.hbox2 = gtk.HBox(True,2)
        self.hbox2.pack_start(self.entry_box,expand=True,fill=True)
        self.hbox2.pack_start(self.value_box,expand=True,fill=True)
        self.frame = gtk.Frame()
        self.frame.set_shadow_type(gtk.SHADOW_IN)
        self.frame.add(self.hbox2)
        self.hbox1.pack_start(self.frame)
        self.hbox1.pack_start(self.act_btn,expand=False,fill=False)
        self.hbox1.pack_start(self.undo_btn,expand=False,fill=False)
        self.hbox1.set_border_width(2)
        self.add(self.hbox1)
        
        # signals and parameters
        self.positioner = positioner
        self.positioner.connect('changed', self._on_value_change)
        self.act_btn.connect('clicked', self._on_activate)
        self.undo_btn.connect('clicked', self._on_undo)
        self.entry_box.connect('activate', self._on_activate)
        self.undo_stack = []
        self.running = False
        self.width = width
        self.format = format

        if self.positioner.units != "":
            label = '%s (%s)' % (label, self.positioner.units)
        self.set_label(label)

        # Set default values from device
        self.set_current( self.positioner.get_position() )
        self.set_target( self.positioner.get_position() )
    
    def set_current(self, val):
        text = self.format % val
        if len(text) > self.width:
            text = "##.##"
        self.value_box.set_text(text)

    def set_target(self,val):
        text = self.format % val
        if len(text) > self.width:
            text = "%s" % val
        self.entry_box.set_text(text)
    
    def stop(self):
        self.running = False
    
    def move(self):
        target = self._get_target()
        self._save_undo()
        self.positioner.move_to(target, wait=False)

    def _get_target(self):
        current = float(self.value_box.get_text())
        try:
            target = float(self.entry_box.get_text())
        except ValueError:
            target = current
        self.set_target(target)
        return target
    
    def _on_value_change(self, obj, val):
        self.set_current(val)
        return True
        
    def _on_activate(self, obj):
        if self.running:
            self.stop()
        else:
            self.move()
        return True
                    
    def _on_undo(self, obj):
        if len(self.undo_stack)>0 and self.running == False:
            target = self._get_undo()
            self.set_target( target )
            self.positioner.move_to(target, wait=False)
        elif self.running:
            self.undo_btn.set_sensitive(True)
        else:
            self.undo_btn.set_sensitive(False)
        return True
 
    def _save_undo(self):
        curr_value = float(self.value_box.get_text())
        self.undo_stack.append(curr_value)
        self.undo_btn.set_sensitive(True)

    def _get_undo(self):
        if len(self.undo_stack) > 1:
            val = self.undo_stack.pop()
        else:
            self.undo_btn.set_sensitive(False)
            val = self.undo_stack.pop()
        return val              

    
            
class MotorEntry(PositionerEntry):
    def __init__(self, positioner, label="", format="%s", width=8):
        PositionerEntry.__init__(self, positioner, label=label, format=format, width=width)
        self.motor = self.positioner
        if self.motor.units != "":
            label = '%s (%s)' % (label, self.motor.units)
        self.set_label(label)
        self.motor.connect('moving', self._on_motion_change)
        self.motor.connect('health', self._on_health_change)
        self.set_sensitive( self.motor.is_healthy() )
               
    def stop(self):
        self.motor.stop()
        self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
 
    def _on_health_change(self, obj, state):
        if state:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
    
    def _on_motion_change(self, obj, motion):
        if motion:
            self.running = True
            self.act_btn.get_child().set_from_stock('gtk-stop',gtk.ICON_SIZE_MENU)
            self.undo_btn.get_child().set_from_file(os.environ['BCM_PATH'] + '/mxdc/gui/images/throbber.gif')
        else:
            self.running = False
            self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
            self.undo_btn.get_child().set_from_stock('gtk-undo',gtk.ICON_SIZE_MENU)
        self.set_current(self.motor.get_position() )
        return True
    
class PositionerLabel(gtk.Label):
    def __init__( self, positioner,  format="%s", width=8):
        gtk.Label.__init__(self, '')
        self.format = format
        self.positioner = positioner
        self.set_current( self.positioner.get_position() )
        self.positioner.connect('changed', self._on_value_change )
        
    def set_current(self, val):
        self.set_text(self.format % (val))

    def _on_value_change(self, widget, val):
        self.set_current(val)
        return True

class VariableLabel(gtk.Label):
    def __init__( self, variable,  format="%s", width=8):
        gtk.Label.__init__(self, '')
        self.format = format
        self.variable = variable
        
        # enable using both PV's and detectors
        if not hasattr(self.variable, 'get_value') and hasattr(self.variable, 'get'):
            self.variable.get_value = self.variable.get
            
        self.set_current( self.variable.get_value() )
        self.variable.connect('changed', self._on_value_change )

    def set_current(self, val):
        self.set_markup(self.format % (val))

    def _on_value_change(self, widget, val):
        self.set_current(val)
        return True

class ShutterButton(gtk.Button):
    def __init__(self, shutter, label):
        gtk.Button.__init__(self)
        self.shutter = shutter
        container = gtk.HBox(False,0)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image)
        container.pack_start(self.label)
        self.add(container)
        
        self.shutter.connect('changed', self._on_state_change)
        self.connect('clicked', self._on_clicked)
        self._on_state_change(None, self.shutter.is_open())
            
    def _on_clicked(self, widget):
        if self.shutter.is_open():
            self.shutter.close()
        else:
            self.shutter.open()    
        
    def _on_state_change(self, obj, state):
        if state:
            self._set_on()
        else:
            self._set_off()
        return True
            
    def _set_on(self):
        self.label.set_text("Close %s" % self.label_text)
        self.image.set_from_stock('gtk-yes', gtk.ICON_SIZE_SMALL_TOOLBAR)
    
    def _set_off(self):
        self.label.set_text("Open %s" % self.label_text)
        self.image.set_from_stock('gtk-no', gtk.ICON_SIZE_SMALL_TOOLBAR)
    
    
class ActiveProgressBar(gtk.ProgressBar):
    def __init__(self):
        gtk.ProgressBar.__init__(self)    
        self.set_fraction(0.0)
        self.set_text('0.0%')
        self.progress_id = None
        self.busy_state = False
      
    def set_busy(self,busy):
        if busy:
            if self.busy_state == False:
                self.progress_id = gobject.timeout_add(100, self.busy)
                self.busy_state = True
        else:
            if self.progress_id:
                gobject.source_remove(self.progress_id)
                self.busy_state = False
                self.progress_id = None

    def busy(self):
        self.pulse()
        self.set_text(self.get_text())
        return True
     
    def busy_text(self,text):
        self.set_text(text)
        self.set_busy(True)
    
    def idle_text(self,text, fraction=None):
        self.set_busy(False)
        if fraction:
            self.set_fraction(fraction)
        self.set_text(text)
    
    def set_complete(self, complete, text=''):
        if self.progress_id:
            gobject.source_remove(self.progress_id)
            self.progress_id = None
        self.set_fraction(complete)
        complete_text = '%0.1f%%  %s' % ((complete * 100), text)
        self.set_text(complete_text)
    
        
    
        
        
        
        
        
