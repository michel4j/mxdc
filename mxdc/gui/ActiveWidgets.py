import gtk, gobject
import os, sys, time
from Widgets import Gauge
from Dialogs import warning

class PositionerEntry(gtk.Frame):
    def __init__( self, positioner, label="",  format="%g",  width=8):
        gtk.Frame.__init__(self, label)

        # create gui layout
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.value_box = gtk.Label()
        self.value_box.set_alignment(1, 0.5)
        self.entry_box = gtk.Entry()
        self.entry_box.set_has_frame(False)
        self.entry_box.set_width_chars(1)
        self.entry_box.set_alignment(1)
        self.act_btn = gtk.Button()
        self.undo_btn =  gtk.Button()
        self.act_btn.add(gtk.image_new_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU))
        self.undo_btn.add(gtk.image_new_from_stock('gtk-undo',gtk.ICON_SIZE_MENU))
        self.undo_btn.set_sensitive(False)
        self.hbox1 = gtk.HBox(False,0)
        self.hbox2 = gtk.HBox(True,0)
        self.hbox2.pack_start(self.entry_box,expand=True,fill=True)
        self.hbox2.pack_start(self.value_box,expand=True,fill=True)
        self.frame = gtk.Frame()
        self.frame.set_shadow_type(gtk.SHADOW_IN)
        self.frame.add(self.hbox2)
        self.hbox1.pack_start(self.frame)
        self.hbox1.pack_start(self.act_btn,expand=False,fill=False)
        self.hbox1.pack_start(self.undo_btn,expand=False,fill=False)
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
            self.undo_btn.get_child().set_from_file(os.environ['BCM_PATH'] + '/mxdc/gui/images/throbber_0.gif')
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
        self.set_markup("<tt>%s</tt>" % (self.format % (val)))

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
        container.set_border_width(2)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image, expand=False, fill=False)
        container.pack_start(self.label, expand=True, fill=True)
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
    

class LinearProgress(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.set_app_paintable(True)
        self.fraction = 0.0
        self.bar_gc = None 
        self.connect('expose-event', self.on_expose)
        self.queue_draw()
        self.color_spec = None
           
    
    def on_expose(self, obj, event):
        if self.bar_gc is None:
            obj.window.clear()
            self.bar_gc = obj.window.new_gc()
            style = self.get_style()
            if self.color_spec:
                self.bar_gc.foreground = self.get_colormap().alloc_color(self.color_spec)
            else:
                self.bar_gc.foreground = style.bg[gtk.STATE_PRELIGHT]
        
        self.draw_gdk()
        return False

    def draw_gdk(self):
        self.window.set_back_pixmap(None, True)
        bar_width = int(self.allocation.width * self.fraction - 3.0)       
        self.window.draw_rectangle(self.bar_gc, False, 0, 0, self.allocation.width-1,
            self.allocation.height-1)
        if bar_width > 0:
            self.window.draw_rectangle(self.bar_gc, True, 2, 2, bar_width-1, 
                self.allocation.height - 4)
             
    def set_fraction(self, fraction):
        self.fraction = max(0.0, min(1.0, fraction))
        self.queue_draw()

    def get_fraction(self):
        return self.fraction
    
    def set_color(self, spec):
        self.color_spec = spec
        
           
class CryojetWidget(gtk.Frame):
    def __init__( self, cryojet, cryo_x):
        gtk.Frame.__init__(self, '')
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.cryojet = cryojet
        self.cryo_x = cryo_x
        self.cryo_x.set_calibrated(True)
        self.cryojet.connect('level', self._on_level)
        self.cryojet.connect('status', self._on_status)
        
        #layout widgets
        hbox1 = gtk.HBox(False, 6)
        hbox2 = gtk.HBox(False, 6)
        hbox3 = gtk.HBox(False, 6)
        vbox  = gtk.VBox(False, 6)
        
        vbox.pack_start(hbox1, expand=False, fill=False)
        
        hsep = gtk.HSeparator()
        hsep.set_size_request(-1,2)
        vbox.pack_start(hsep, expand=False, fill=False)

        vbox.pack_start(hbox2, expand=False, fill=False)
        vbox.pack_start(hbox3)
        self.add(vbox)
        
        # layout the gauge section
        gauge_box = gtk.VBox(False, 3)
        lb = gtk.Label('')
        lb.set_markup('N<sub>2</sub> Level')
        self.level_gauge = Gauge(0,100,5,3)
        self.level_gauge.set_property('units','%')
        self.level_gauge.set_property('low', 20.0)
        self.level_gauge.value = self.cryojet.level
        gauge_box.pack_start(self.level_gauge, expand=True, fill=True)
        gauge_box.pack_start(lb, expand=True, fill=True)
        hbox1.pack_start(gauge_box, expand=True, fill=True)
        
        # Status section
        status_tbl = gtk.Table(4,3,False)
        status_tbl.set_col_spacings(6)
        tbl_data = {
            'temp': ('Temperature:', 0, 'Kelvin', self.cryojet.temperature, 'temperature'),
            'smpl': ('Sample Flow:', 1, 'L/min', self.cryojet.sample_flow, 'sample-flow'),
            'shld': ('Shield Flow:', 2, 'L/min', self.cryojet.shield_flow, 'shield-flow'),
            }
        self.text_monitors = {}
        for k,v in tbl_data.items():
            lb = gtk.Label(v[0])
            lb.set_alignment(1,0.5)
            status_tbl.attach(lb, 0, 1, v[1], v[1]+1)
            lb = gtk.Label('%0.1f' % v[3] )
            lb.set_alignment(1,0.5)
            self.cryojet.connect(v[4], self._on_val_changed, k)
            self.text_monitors[k] = lb
            status_tbl.attach(lb, 1,2,v[1], v[1]+1)
            status_tbl.attach(gtk.Label(v[2]), 2,3, v[1], v[1]+1)

        self.sts_text = gtk.Label('filling')
        self.sts_text.set_text('%s' % self.cryojet.status)
        lb = gtk.Label('Status:')
        lb.set_alignment(1,0.5)
        status_tbl.attach(lb, 0,1,3,4)
        status_tbl.attach(self.sts_text, 1,3,3,4)     
        hbox1.pack_end(status_tbl, expand=True, fill=True)
        
        
        # Flow Annealing section
        size_group = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        anneal_frame = gtk.Frame('<b>Flow Control Annealing:</b>')    
        anneal_frame.set_shadow_type(gtk.SHADOW_NONE)
        anneal_frame.get_label_widget().set_use_markup(True)
        
        align = gtk.Alignment()
        align.set(0.5,0.5,1,1)
        align.set_padding(0,0,12,0)
        anneal_frame.add(align)
        
        self.start_anneal_btn = gtk.Button('Anneal')
        self.stop_anneal_btn = gtk.Button('Stop')
        size_group.add_widget( self.start_anneal_btn )
        size_group.add_widget( self.stop_anneal_btn )
        self.anneal_prog = gtk.ProgressBar()
        
        ahbox = gtk.HBox(False,6)
        fvbox = gtk.VBox(True, 6)
        self.anneal_tools = gtk.HBox(True, 6)
        self.duration_en = gtk.Entry()
        self.duration_en.set_alignment(1)
        self.duration_en.set_width_chars(5)
        self.duration_en.set_text('%0.1f' % 5.0)
        self.anneal_tools.pack_start(gtk.Label('Duration (sec):'), expand=True, fill=True)
        self.anneal_tools.pack_start(self.duration_en, expand=True, fill=True)
        self.anneal_tools.pack_start(self.start_anneal_btn, expand=True, fill=True)
        fvbox.pack_start(self.anneal_tools, expand=False, fill=False)
        self.anneal_status = gtk.HBox(False, 6)
        self.anneal_status.set_sensitive(False)
        self.anneal_status.pack_start(self.anneal_prog,expand=True, fill=True)
        self.anneal_status.pack_end(self.stop_anneal_btn, expand=True, fill=True)
        fvbox.pack_start(self.anneal_status, expand=False, fill=False)
        fvbox.pack_end(gtk.Label(''), expand=True, fill=True)
        ahbox.pack_start(fvbox)
        align.add(ahbox)
        hbox2.pack_end(anneal_frame,expand=True, fill=True)
        self.start_anneal_btn.connect('clicked', self._start_anneal)
        self.stop_anneal_btn.connect('clicked', self._stop_anneal)

        # Cryo Nozzle section
        noz_frame = gtk.Frame('<b>Nozzle Control:</b>')    
        noz_frame.set_shadow_type(gtk.SHADOW_NONE)
        noz_frame.get_label_widget().set_use_markup(True)
        
        align = gtk.Alignment()
        align.set(0.5,0.5,1,1)
        align.set_padding(0,0,12,0)
        noz_frame.add(align)
        ctable = gtk.Table(2,3,False)
        ctable.set_col_spacings(3)
        ctable.set_row_spacings(3)
        ctable.attach(gtk.Label('Position (mm):'), 0,1,0,1, xoptions=gtk.EXPAND|gtk.FILL)
        ctable.attach(PositionerLabel(self.cryo_x, format='%0.1f'), 1, 2, 0,1, xoptions=gtk.EXPAND|gtk.FILL)
        self.retract1_btn = gtk.Button('Retract 1 mm')
        self.retract5_btn = gtk.Button('Retract 5 mm')
        self.restore_btn = gtk.Button('Restore')
        ctable.attach(self.retract1_btn, 0,1,1,2, xoptions=gtk.EXPAND|gtk.FILL)
        ctable.attach(self.retract5_btn, 1,2,1,2, xoptions=gtk.EXPAND|gtk.FILL)
        ctable.attach(self.restore_btn, 0,2,2,3, xoptions=gtk.EXPAND|gtk.FILL)
        align.add(ctable)
        hbox2.pack_start(noz_frame,expand=True, fill=True)
        self._restore_anneal_id = None
        self._progress_id = None
        self._annealed_time = 0
        gobject.timeout_add(500, self._blink_status)
        self.retract1_btn.connect('clicked', self._on_nozzle_move, 1)
        self.retract5_btn.connect('clicked', self._on_nozzle_move, 5)
        self.restore_btn.connect('clicked', self._on_nozzle_move, -15)
        
        #autocalibration of nozzle motor
        self.cryo_x.CCW_LIM.connect('changed', self._auto_calib_nozzle)
    
    def _blink_status(self):
        if self.sts_text.get_property('visible') == True:
            self.sts_text.hide()
        else:
            self.sts_text.show()
        return True
                
    def _on_nozzle_move(self, obj, pos):
        self.cryo_x.move_by(pos)
        
    def _auto_calib_nozzle(self, obj, val):
        if val == 1:
            self.cryo_x.set_position(0.0)
        
    def _on_level(self, obj, val):
        self.level_gauge.value = val
        return False

    def _on_status(self, obj, val):
        self.status.set_text('%s' % val)
        return False

    def _on_val_changed(self, obj, val, key):
        self.text_monitors[key].set_text('%0.1f' % val)
        return False
    
    def _start_anneal(self, obj=None):
        try:
            duration = float( self.duration_en.get_text() )
        except:
            self.duration_en.set_text('0')
            return
        msg1 = 'This procedure may damage your sample'
        msg2  = 'Flow control annealing will turn off the cold stream for the specified '
        msg2 += 'duration of <b>"%0.1f"</b> seconds. The outer dry nitrogen shroud remains on to protect the crystal ' % duration
        msg2 += 'from icing. However this procedure may damage the sample.\n\n'
        msg2 += 'Are you sure you want to continue?'
            
        response = warning(msg1, msg2, buttons=(('Cancel', gtk.BUTTONS_CANCEL), ('Anneal', gtk.BUTTONS_OK)))
        if response == gtk.BUTTONS_OK:
            self.anneal_tools.set_sensitive(False)
            self.anneal_status.set_sensitive(True)
            self._annealed_time = 0
            self.cryojet.stop_flow()
            dur = max(0.0, (duration-0.5*1000))
            self._restore_anneal_id = gobject.timeout_add(duration*1000, self._stop_anneal)
            self._progress_id = gobject.timeout_add(1000, self._update_progress, duration)
            
    def _stop_anneal(self, obj=None):
        self.cryojet.resume_flow()
        self.anneal_tools.set_sensitive(True)
        self.anneal_status.set_sensitive(False)
        self.anneal_prog.set_fraction(0.0)
        self.anneal_prog.set_text('')
        if self._restore_anneal_id:
            gobject.source_remove(self._restore_anneal_id)
            self._restore_anneal_id = None
        if self._progress_id:
            gobject.source_remove(self._progress_id)
            self._progress_id = None
        return False

    def _update_progress(self, duration):
        if self._annealed_time < duration:
            self._annealed_time += 1
            self.anneal_prog.set_fraction(self._annealed_time/duration)
            self.anneal_prog.set_text('%0.1f sec' % self._annealed_time)
            return True
        else:
            return False
