import os
import sys
import time
import gtk
import gtk.glade
import gobject

from gauge import Gauge
from dialogs import warning


class ActiveHScale(gtk.HScale):
    def __init__( self, context, min=0.0, max=1.0):
        gtk.HScale.__init__(self)
        self.context = context
        self.set_value_pos(gtk.POS_RIGHT)
        self.set_digits(1)
        self.set_range(min, max)
        self.set_adjustment(gtk.Adjustment(0.0,0,5, 0.1,0,0))
        self.set_update_policy(gtk.UPDATE_CONTINUOUS)
        self._handler_id = self.connect('value-changed', self._on_scale_changed)
        self.context.connect('changed', self._on_feedback_changed)
    
    def _on_scale_changed(self, obj):
        target = self.get_value()
        if hasattr(self.context, 'move_to'):
            self.context.move_to( target )
        elif hasattr(self.context, 'set'):
            self.context.set(target)
        
    def _on_feedback_changed(self, obj, val):
        # we need to prevent an infinite loop by temporarily suspending
        # the _on_scale_changed handler
        self.context.handler_block(self._handler_id)
        self.set_value(val)
        self.context.handler_unblock(self._handler_id)
        
class ActiveLabel(gtk.Label):
    def __init__( self, context, format="%s", show_units=True):
        gtk.Label.__init__(self, '')
        self.format = format
        self.context = context
        self.context.connect('changed', self._on_value_change )
                  
        if not hasattr(self.context, 'units') or not show_units:
            self._units = ''
        else :
            self._units = self.context.units
                            
    def _on_value_change(self, obj, val):
        self.set_markup("%s %s" % (self.format % (val), self._units))
        return True
  
class ActiveEntry(gtk.VBox):
    def __init__( self, device, label=None,  format="%g",  width=8):
        gtk.VBox.__init__(self, label)

        # create gui layout
        
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/active_entry.glade'), 
                                  'active_entry')
        
        self._active_entry = self._xml.get_widget('active_entry')
        self._fbk_label = self._xml.get_widget('fbk_label')
        self._entry = self._xml.get_widget('entry')
        self._action_btn = self._xml.get_widget('action_btn')
        self._action_icon = self._xml.get_widget('action_icon')
        self._label = self._xml.get_widget('label')
                
        self.pack_start(self._active_entry)
        
        self._fbk_label.set_alignment(1, 0.5)
        self._entry.set_width_chars(1)
        self._entry.set_alignment(1)
        
        # signals and parameters
        self.device = device
        self.device.connect('changed', self._on_value_change)

        self._action_btn.connect('clicked', self._on_activate)
        self._entry.connect('activate', self._on_activate)
        
        self._first_change = True
        self.running = False
        self.width = width
        self.format = format
        
        if label is None:
            label = self.device.name
        
        if self.device.units != "":
            label = '%s (%s)' % (label, self.device.units)
        self._label.set_markup("%s" % (label,))

    
    def set_feedback(self, val):
        text = self.format % val
        if len(text) > self.width:
            text = "##.##"
        self._fbk_label.set_markup('%s' % (text,))

    def set_target(self,val):
        text = self.format % val
        self._entry.set_text(text)
    
    def stop(self):
        self.running = False
    
    def apply(self):
        target = self._get_target()
        if hasattr(self.device, 'move_to'):
            self.device.move_to(target)
        elif hasattr(self.device, 'set'):
            self.device.set(target)
        

    def _get_target(self):
        feedback = self._fbk_label.get_text()
        try:
            target = float(self._entry.get_text())
        except ValueError:
            target = feedback
            self.set_target(target)
        return target
    
    def _on_value_change(self, obj, val):
        self.set_feedback(val)
        return True
        
    def _on_activate(self, obj):
        if self.running:
            self.stop()
        else:
            self.apply()
        return True
                    
    
            
class MotorEntry(ActiveEntry):
    def __init__(self, mtr, label=None, format="%0.3f", width=8):
        ActiveEntry.__init__(self, mtr, label=label, format=format, width=width)

        self.device.connect('moving', self._on_motion_change)
        self.device.connect('health', self._on_health_change)
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
           
    def stop(self):
        self.device.stop()
        self._action_icon.set_from_stock('gtk-apply',    gtk.ICON_SIZE_MENU)
 
    def _on_health_change(self, obj, state):
        if state:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
    
    def _on_motion_change(self, obj, motion):
        if motion:
            self.running = True
            self._action_icon.set_from_animation(self._animation)
        else:
            self.running = False
            self.set_target(self.device.get_position())
            self._action_icon.set_from_stock('gtk-apply',gtk.ICON_SIZE_MENU)
        self.set_feedback(self.device.get_position())
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
    def __init__(self, cryojet):
        gtk.Frame.__init__(self, '')
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.cryojet = cryojet
        self.cryojet.nozzle.configure(calib=True)
        self.cryojet.sample_flow.connect('changed', self._on_level)
        
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
