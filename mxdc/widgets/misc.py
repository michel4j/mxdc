import os
import sys
import time
import gtk
import gtk.glade
import gobject
import pango

from gauge import Gauge
from dialogs import warning

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class ActiveHScale(gtk.HScale):
    def __init__( self, context, min=0.0, max=100.0):
        gtk.HScale.__init__(self)
        self.context = context
        self.set_value_pos(gtk.POS_RIGHT)
        self.set_digits(1)
        self.set_range(min, max)
        self.set_adjustment(gtk.Adjustment(0.0, min, max, (max-min)/100.0, 0, 0))
        self.set_update_policy(gtk.UPDATE_CONTINUOUS)
        self._handler_id = self.connect('value-changed', self._on_scale_changed)
        self.context.connect('changed', self._on_feedback_changed)
        self._feedback = False
        
    def _on_scale_changed(self, obj):
        if self._feedback:
            return
        target = self.get_value()
        if hasattr(self.context, 'move_to'):
            self.context.move_to( target )
        elif hasattr(self.context, 'set'):
            self.context.set(target)
        
    def _on_feedback_changed(self, obj, val):
        # we need to prevent an infinite loop by temporarily suspending
        # the _on_scale_changed handler
        #self.context.handler_block(self._handler_id)
        self._feedback = True
        self.set_value(val)
        self._feedback = False
        #self.context.handler_unblock(self._handler_id)
        
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
    def __init__( self, device, label=None,  format="%g",  width=10):
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
        font_desc = pango.FontDescription()
        #font_desc.set_family('#monospace')
        #self._fbk_label.modify_font(font_desc)


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
        self._last_signal = 0
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
        self._fbk_label.set_markup('%8s' % (text,))

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
        if time.time() - self._last_signal > 0.1:
            self.set_feedback(val)
            self._last_signal = time.time()
        if self._first_change:
            self.set_target(val)
            self._first_change = False
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
        self._action_icon.set_from_stock('gtk-apply', gtk.ICON_SIZE_MENU)
 
    def _on_health_change(self, obj, state):
        if state:
            self._entry.set_sensitive(True)
            self._action_icon.set_from_stock('gtk-apply', gtk.ICON_SIZE_MENU)
        else:
            self._entry.set_sensitive(False)
            self._action_icon.set_from_stock('gtk-dialog-warning', gtk.ICON_SIZE_MENU)
            
    
    def _on_motion_change(self, obj, motion):
        if motion:
            self.running = True
            self._action_icon.set_from_animation(self._animation)
        else:
            self.running = False
            self.set_target(self.device.get_position())
            self.set_feedback(self.device.get_position())
            self._action_icon.set_from_stock('gtk-apply',gtk.ICON_SIZE_MENU)
        self.set_feedback(self.device.get_position())
        return True
    


class ShutterButton(gtk.ToggleButton):
    def __init__(self, shutter, label, open_only=False):
        gtk.ToggleButton.__init__(self)
        self.shutter = shutter
        self.open_only = open_only
        container = gtk.HBox(False,0)
        container.set_border_width(2)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image, expand=False, fill=False)
        container.pack_start(self.label, expand=True, fill=True)
        self.add(container)
        self._set_off()
        self.shutter.connect('changed', self._on_state_change)
        self.connect('clicked', self._on_clicked)
            
    def _on_clicked(self, widget):
        if self.shutter.get_state():
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
        if self.open_only:
            self.set_sensitive(False)
        else:
            self.label.set_text(self.label_text)
        self.image.set_from_stock('gtk-yes', gtk.ICON_SIZE_SMALL_TOOLBAR)
    
    def _set_off(self):
        self.set_sensitive(True)
        self.label.set_text(self.label_text)
        self.image.set_from_stock('gtk-no', gtk.ICON_SIZE_SMALL_TOOLBAR)

class ScriptButton(gtk.Button):
    def __init__(self, script, label):
        gtk.Button.__init__(self)
        self.script = script
        container = gtk.HBox(False,0)
        container.set_border_width(2)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image, expand=False, fill=False)
        container.pack_start(self.label, expand=True, fill=True)
        self.add(container)
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
        self.tooltip = gtk.Tooltips()
        self.tooltip.set_tip(self, self.script.description)
        self._set_off()
     
        self.script.connect('done', self._on_state_change)
        self.script.connect('error', self._on_state_change)
        self.connect('clicked', self._on_clicked)
            
    def _on_clicked(self, widget):
        if not self.script.is_active():
            self.script.start()
            self._set_on()  
        
    def _on_state_change(self, obj):
        self._set_off()
        return True
            
    def _set_on(self):
        self.image.set_from_animation(self._animation)
        self.label.set_sensitive(False)
        #self.set_relief(gtk.RELIEF_NONE)
    
    def _set_off(self):
        self.image.set_from_stock('gtk-execute', gtk.ICON_SIZE_SMALL_TOOLBAR)
        self.label.set_sensitive(True)
        #self.set_relief(gtk.RELIEF_NORMAL)


class ShutterStatus(gtk.HBox):
    def __init__(self, shutter):
        gtk.HBox.__init__(self, False, 0)
        self.shutter = shutter
        self.set_border_width(2)
        self.image = gtk.Image()
        self.pack_start(self.image)
        
        self.shutter.connect('changed', self._on_state_change)
                    
    def _on_state_change(self, obj, state):
        if state:
            self._set_on()
        else:
            self._set_off()
        return True
            
    def _set_on(self):
        self.image.set_from_stock('gtk-yes', gtk.ICON_SIZE_MENU)
    
    def _set_off(self):
        self.image.set_from_stock('gtk-no', gtk.ICON_SIZE_MENU)
    

class StatusDisplay(gtk.HBox):
    def __init__(self, icon_list, message):
        gtk.HBox.__init__(self, False, 0)
        self.message = message
        self.icon_list = icon_list
        self.image = gtk.Image()
        self.label = gtk.Label()
        self.pack_start(self.image, expand=False, fill=False)
        self.pack_start(self.label, expand=True, fill=True)
                                        
    def set_state(self, val=None, message=None):
        if val is not None:
            if len(self.icon_list) > val > 0:
                self.image.set_from_stock(self.icon_list[val], gtk.ICON_SIZE_MENU)
        if message is not None:
            self.message = message
            self.label.set_markup(message)
        
        
        
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
        self.color_spec = None
        self.bg_spec = None
        self.queue_draw()
           
    
    def on_expose(self, obj, event):
        if self.bar_gc is None:
            obj.window.clear()
            self.bar_gc = obj.window.new_gc()
            style = self.get_style()
            if self.color_spec:
                self.bar_gc.foreground = self.get_colormap().alloc_color(self.color_spec)
            else:
                self.bar_gc.foreground = style.fg[gtk.STATE_PRELIGHT]
            if self.bg_spec:
                self.bar_gc.background = self.get_colormap().alloc_color(self.bg_spec)
            else:
                self.bar_gc.background = style.bg[gtk.STATE_PRELIGHT]
        
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
    
    def set_color(self, spec=None, bg_spec=None):
        self.color_spec = spec
        self.bg_spec = bg_spec
        
           
class CryojetWidget(gtk.Frame):
    def __init__(self, cryojet):
        gtk.Frame.__init__(self, '')
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.cryojet = cryojet
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'cryo_widget.glade'), 
                                  'cryo_widget')
        self.cryo_widget = self._xml.get_widget('cryo_widget')
        self.add(self.cryo_widget)
        self.anneal_prog = self._xml.get_widget('anneal_progress')
        self.status_table = self._xml.get_widget('status_table')
        self.status_box = self._xml.get_widget('status_box')
        self.start_anneal_btn = self._xml.get_widget('start_anneal_btn')
        self.stop_anneal_btn = self._xml.get_widget('stop_anneal_btn')
        self.status_text = self._xml.get_widget('status_text')
        self.duration_entry = self._xml.get_widget('duration_entry')
        self.retract1_btn = self._xml.get_widget('retract1_btn')
        self.retract5_btn = self._xml.get_widget('retract5_btn')
        self.restore_btn = self._xml.get_widget('restore_btn')
        self.anneal_table = self._xml.get_widget('anneal_table')
        self.nozzle_table = self._xml.get_widget('nozzle_table')
        self.level_frame = self._xml.get_widget('level_frame')
        
        # layout the gauge section
        self.level_gauge = Gauge(0,100,5,3)
        self.level_gauge.set_property('units','%')
        self.level_gauge.set_property('low', 20.0)
        self.level_frame.add(self.level_gauge)
        self.cryojet.level.connect('changed', self._on_level)
        
        # Status section
        tbl_data = {
            'temp': (0, self.cryojet.temperature),
            'smpl': (1, self.cryojet.sample_flow),
            'shld': (2, self.cryojet.shield_flow),
            'sts' : (3, self.cryojet.fill_status),
            }
        for k,v in tbl_data.items():
            lb = ActiveLabel(v[1])
            lb.set_alignment(0.5, 0.5)
            self.status_table.attach(lb, 1, 2, v[0], v[0]+1)

        self.duration_entry.set_alignment(0.5)
        self.start_anneal_btn.connect('clicked', self._start_anneal)
        self.stop_anneal_btn.connect('clicked', self._stop_anneal)
        
        self.nozzle_table.attach(ActiveLabel(self.cryojet.nozzle, format='%0.1f'), 1,2,0,1)
        self._restore_anneal_id = None
        self._progress_id = None
        self._annealed_time = 0
        gobject.timeout_add(500, self._blink_status)
        self.stop_anneal_btn.set_sensitive(False)
        self.retract1_btn.connect('clicked', self._on_nozzle_move, 1)
        self.retract5_btn.connect('clicked', self._on_nozzle_move, 5)
        self.restore_btn.connect('clicked', self._on_nozzle_move, -15)
        
        #autocalibration of nozzle motor
        self.auto_calib_id = None
    
    def _blink_status(self):
        if self.status_text.get_property('visible') == True:
            self.status_text.hide()
        else:
            self.status_text.show()
        return True
                
    def _on_nozzle_move(self, obj, pos):
        if self.auto_calib_id is None:
            #FIXME: this is ugly
            self.cryojet.nozzle.CCW_LIM.connect('changed', self._auto_calib_nozzle)
        self.cryojet.nozzle.move_by(pos)
        
    def _auto_calib_nozzle(self, obj, val):
        if val == 1:
            self.cryojet.nozzle.configure(reset=0.0)
        
    def _on_level(self, obj, val):
        self.level_gauge.value = val/10.0
        return False

    def _on_status(self, obj, val):
        self.status.set_text('%s' % val)
        return False
    
    def _start_anneal(self, obj=None):
        try:
            duration = float( self.duration_entry.get_text() )
        except:
            self.duration_entry.set_text('0.0')
            return
        msg1 = 'This procedure may damage your sample'
        msg2  = 'Flow control annealing will turn off the cold stream for the specified '
        msg2 += 'duration of <b>"%0.1f"</b> seconds. The outer dry nitrogen shroud remains on to protect the crystal ' % duration
        msg2 += 'from icing. However this procedure may damage the sample.\n\n'
        msg2 += 'Are you sure you want to continue?'
            
        response = warning(msg1, msg2, buttons=(('Cancel', gtk.BUTTONS_CANCEL), ('Anneal', gtk.BUTTONS_OK)))
        if response == gtk.BUTTONS_OK:
            self.anneal_table.set_sensitive(False)
            self._annealed_time = 0
            self.cryojet.stop_flow()
            dur = max(0.0, (duration-0.5*1000))
            self._restore_anneal_id = gobject.timeout_add(duration*1000, self._stop_anneal)
            self._progress_id = gobject.timeout_add(1000, self._update_progress, duration)
            
    def _stop_anneal(self, obj=None):
        self.cryojet.resume_flow()
        self.anneal_table.set_sensitive(True)
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
