#!/usr/bin/env python

import gtk, gobject
import sys, time

class NewEntry(gtk.Frame):
    def __init__( self, label="Test", name=None,  width=8):
        gtk.Frame.__init__(self, label)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.value_box = gtk.Label()
        self.value_box.set_text('12.658')
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
        self.act_btn.connect('clicked', self.on_act_btn_clicked)
        self.undo_btn.connect('clicked', self.on_undo_btn_clicked)
        self.entry_box.connect('activate', self.on_act_btn_clicked)
        self.running = False
        self.undo_stack = []
        self.undo_btn.set_sensitive(False)
        self.last_event = 0
        
    def set_position(self, val, prec=5):
        self.value_box.set_text("%g" % val)

    def set_target(self,val, prec=5):
        self.entry_box.set_text("%g" % val)
    
    def get_position(self):
        return float( self.value_box.get_text() )       

    def on_act_btn_clicked(self,widget):
        if self.running:
            self.stop()
        else:
            self.move()
        return True
        
    def on_activate(self,widget):
        self.move()
        return True
            
    def on_undo_btn_clicked(self,widget):
        if len(self.undo_stack)>0:
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
    
    def update_pos(self, pos):
        self.set_position(pos)

    def update_state(self, state):
        pass
            
    def on_monitor_pos(self,widget, position):
        self.update_pos(position)
        return True
    
    def on_monitor_state(self, widget, state):
        self.update_state(state)
        return True

class ActiveEntry(NewEntry):
    def __init__(self, label, positioner, width=8):
        NewEntry.__init__(self, label=label, width=width)
        self.motor = positioner
        self.set_position( self.motor.get_position() )
        self.set_target( self.motor.get_position() )
        label = '%s (%s)' % (label, self.motor.units)
        self.set_label(label)
        self.motor.connect('changed', self.on_monitor_pos )
        self.motor.connect('moving', self.on_monitor_state, True )
        self.motor.connect('stopped', self.on_monitor_state, False )
               
    def move(self, save=True):
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
 
    def update_state(self,state):
        if state == None:
            state = self.motor.is_moving()
        if state:
            self.running = True
            self.act_btn.get_child().set_from_stock('gtk-stop',gtk.ICON_SIZE_MENU)
        else:
            self.running = False
            self.act_btn.get_child().set_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU)
        self.set_position(self.motor.get_position() )
        return True             

    def on_monitor_pos(self,widget, position):
        self.set_position(position)
        return True
    
    def on_monitor_state(self, widget, state):
        self.update_state(state)
        return True

class ActiveLabel(gtk.Label,gobject.GObject):
    def __init__( self, positioner,  width=8):
        gtk.Label.__init__(self, '')
        gobject.GObject.__init__(self)
        self.positioner = positioner
        self.update_value( self.positioner.get_position() )
        self.positioner.connect('changed', self.on_monitor_pos )
        
    def update_value(self, val):
        self.set_text("%s %s" % (val, self.positioner.units))

    def on_monitor_pos(self, widget, val):
        self.update_value(val)
        return True
