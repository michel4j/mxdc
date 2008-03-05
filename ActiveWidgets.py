#!/usr/bin/env python

import gtk, gobject
import sys, time

class NewEntry(gtk.Frame):
    def __init__( self, label="Test", format="%g",  width=8):
        gtk.Frame.__init__(self, label)
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
        self.running = False
        self.act_btn.connect('clicked', self.on_act_btn_clicked)
        self.undo_btn.connect('clicked', self.on_undo_btn_clicked)
        self.entry_box.connect('activate', self.on_act_btn_clicked)
        self.undo_stack = []
        self.undo_btn.set_sensitive(False)
        self.last_event = 0
        self.width = width
        self.format = format
        self.throbber = gtk.Image()
        self.throbber.set_from_file('images/throbber.gif')
    
    def set_position(self, val):
        text = self.format % val
        if len(text) > self.width:
            text = "%8g" % val
        self.value_box.set_text(text)

    def set_target(self,val):
        text = self.format % val
        if len(text) > self.width:
            text = "%8g" % val
        self.entry_box.set_text(text)
    
    def get_position(self):
        return float( self.value_box.get_text() )       

    def _check_value(self):
        current = float(self.value_box.get_text())
        try:
            target = float(self.entry_box.get_text())
        except:
            target = current
        self.set_target(target)
        return True
        
    def on_act_btn_clicked(self,widget):
        if not self._check_value():
            return True
        if self.running:
            self.stop()
        else:
            self.move()
        return True
        
    def on_activate(self,widget):
        self.move()
        return True
            
    def on_undo_btn_clicked(self,widget):
        if len(self.undo_stack)>0 and self.running == False:
            self.set_target( self._get_undo() )
            self.move(save=False)
        else:
            self.undo_btn.set_sensitive(False)
        return True

    def stop(self):
        self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
        self.running = False
    
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

    def move(self, save=True):
        if save:
            self._save_undo()
        target = float(self.entry_box.get_text())
        self.set_position(target)
    
            
class ActiveEntry(NewEntry):
    def __init__(self, label, positioner, format="%s", width=8):
        NewEntry.__init__(self, label=label, format=format, width=width)
        self.motor = positioner
        try:
            self.set_position( self.motor.get_position() )
            self.set_target( self.motor.get_position() )
        except:
            print 'Positioner "%s" not online' % self.motor.name
        if self.motor.units != "":
            label = '%s (%s)' % (label, self.motor.units)
        self.set_label(label)
        self.motor.connect('changed', self.on_monitor_pos )
        self.motor.connect('moving', self.on_monitor_state)
        self.motor.connect('valid', self.on_validate)
               
    def move(self, save=True):
        self.check_motor()
        try:
            target = float(self.entry_box.get_text())
        except:
            target = float(self.value_box.get_text())
            self.set_target(target)
            return            
        if save:
            self._save_undo()
        self.motor.move_to(target,wait=False)

    def stop(self):
        self.motor.stop()
        self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
 
    def on_validate(self, widget, valid):
        if valid:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)

    def on_monitor_pos(self,widget, position):
        self.set_position(position)
        return True
    
    def on_monitor_state(self, widget, state):
        if state == None:
            state = self.motor.is_moving()
        if state:
            self.running = True
            self.act_btn.get_child().set_from_stock('gtk-stop',gtk.ICON_SIZE_MENU)
            img, mask = self.throbber.get_image()
            self.undo_btn.get_child().set_from_image(img, mask)
        else:
            self.running = False
            self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
            self.undo_btn.get_child().set_from_stock('gtk-undo',gtk.ICON_SIZE_MENU)
        self.set_position(self.motor.get_position() )
        return True
    
    def check_motor(self, widget=None, event=None):
        if self.motor.is_valid():
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)        

class ActiveLabel(gtk.Label):
    def __init__( self, positioner,  format="%s", width=8):
        gtk.Label.__init__(self, '')
        self.format = format
        self.positioner = positioner
        try:
            self.update_value( self.positioner.get_position() )
        except:
            print 'Positioner "%s" not online' % self.positioner.name
        
        self.positioner.connect('changed', self.on_monitor_pos )
        
    def update_value(self, val):
        self.set_text(self.format % (val))

    def on_monitor_pos(self, widget, val):
        self.update_value(val)
        return True

class DiagnosticLabel(gtk.Label):
    def __init__( self, variable,  format="%s", interval=500, width=8):
        gtk.Label.__init__(self, '')
        self.format = format
        self.variable = variable
        self.interval = interval
        self.update_value( self.variable.get_value() )
        gobject.timeout_add(self.interval, self.on_update)

    def update_value(self, val):
        self.set_text(self.format % (val))

    def on_update(self, widget=None):
        self.update_value( self.variable.get_value() )
        return True

class ShutterButton(gtk.Button):
    def __init__(self, shutter, label=None):
        gtk.Button.__init__(self)
        self.shutter = shutter
        container = gtk.HBox(False,0)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image)
        container.pack_start(self.label)
        self.add(container)
        
        if shutter.is_open():
            self._set_on()
        else:
            self._set_off()
        self.shutter.connect('changed', self.on_state_change)
        self.connect('clicked', self.on_clicked)
            
    def on_clicked(self, widget):
        if self.shutter.is_open():
            self.shutter.close()
        else:
            self.shutter.open()    
        
    def on_state_change(self, widget, state):
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
    
        
    
        
        
        
        
        
