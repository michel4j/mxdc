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
    def __init__( self, context, format="%s", show_units=True, range=None):
        gtk.Label.__init__(self, '')

        self.set_alignment(0.5,0.5)
        self.format = format
        self.context = context
        self.context.connect('changed', self._on_value_change )
        self.range = range
        try:
            self.context.connect('alarm', self._on_alarm )
        except:
            #No alarm signal present
            pass
                  
        if not hasattr(self.context, 'units') or not show_units:
            self._units = ''
        else :
            self._units = self.context.units
                            
    def _on_value_change(self, obj, val):
        if self.range is not None:
            if not (self.range[0] >= val <= self.range[1]):
                self.format = '<span color="red">%s</span>' % format
        self.set_markup("%s %s" % (self.format % (val), self._units))
        return True

    def _on_alarm(self, obj, alrm):
        alarm, severity = alrm
        print alarm, severity
        
class ActiveEntry(gtk.VBox):
    #_border = gtk.Border(3,3,4,4)
    def __init__( self, device, label=None,  format="%g",  width=10):
        gtk.VBox.__init__(self, label)
        self._sizegroup_h = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        self._sizegroup_v = gtk.SizeGroup(gtk.SIZE_GROUP_VERTICAL)
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

        self._sizegroup_h.add_widget(self._entry)
        self._sizegroup_h.add_widget(self._fbk_label)
        self._sizegroup_v.add_widget(self._entry)
        self._sizegroup_v.add_widget(self._fbk_label)
        #self._sizegroup_v.add_widget(self._action_btn)

        #font_desc.set_family('#monospace')
        #self._fbk_label.modify_font(font_desc)


        self.pack_start(self._active_entry)
        
        self._fbk_label.set_alignment(1, 0.5)
        #self._entry.set_inner_border(self._border)
        
        self._entry.set_width_chars(1)
        self._entry.set_alignment(1)
        
        # signals and parameters
        self.device = device
        self.device.connect('changed', self._on_value_changed)
        self.device.connect('active', self._on_active_changed)
        self._action_btn.connect('clicked', self._on_activate)
        self._entry.connect('activate', self._on_activate)
        
        self._first_change = True
        self._last_signal = 0
        self.running = False
        self.width = width
        self.number_format = format
        self.format = self.number_format
        
        if label is None:
            label = self.device.name
        
        if self.device.units != "":
            label = '%s (%s)' % (label, self.device.units)
        self._label.set_markup("<small><b>%s</b></small>" % (label,))

    
    def set_feedback(self, val):
        text = self.number_format % val
        if len(text) > self.width:
            text = "##.##"
        self._fbk_label.set_markup('%8s' % (text,))

    def set_target(self,val):
        text = self.number_format % val
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
    
    def _on_value_changed(self, obj, val):
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
    
    def _set_active(self, state):
        if state:
            self._entry.set_sensitive(True)
            self._action_btn.set_sensitive(True)
        else:
            self._entry.set_sensitive(False)
            self._action_btn.set_sensitive(False)

    def _on_active_changed(self, obj, state):
        self._set_active(state)
            
                    
    
            
class MotorEntry(ActiveEntry):
    def __init__(self, mtr, label=None, format="%0.3f", width=8):
        ActiveEntry.__init__(self, mtr, label=label, format=format, width=width)
        self._set_active(False)
        self.device.connect('busy', self._on_motion_changed)
        self.device.connect('health', self._on_health_changed)
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
           
    def stop(self):
        self.device.stop()
        self._action_icon.set_from_stock('gtk-apply', gtk.ICON_SIZE_MENU)
 
    def _on_health_changed(self, obj, state, msg=None):
        if state == 0:
            self._fbk_label.modify_fg(gtk.STATE_NORMAL, None)
            self._action_icon.set_from_stock('gtk-apply', gtk.ICON_SIZE_MENU)
        else:
            self._fbk_label.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("red"))
            self._action_icon.set_from_stock('gtk-dialog-warning', gtk.ICON_SIZE_MENU)
            
    
    def _on_motion_changed(self, obj, motion):
        if motion:
            self.running = True
            self._action_icon.set_from_animation(self._animation)
        else:
            self.running = False
            self.set_target(self.device.get_position())
            self._action_icon.set_from_stock('gtk-apply',gtk.ICON_SIZE_MENU)
        self.set_feedback(self.device.get_position())
        return True
    


class ShutterButton(gtk.ToggleButton):
    def __init__(self, shutter, label, open_only=False, action_label=False):
        gtk.ToggleButton.__init__(self)
        self.shutter = shutter
        self.open_only = open_only
        self.action_label = action_label
        alignment = gtk.Alignment(0.5,0.5,0.0,0.0)
        container = gtk.HBox(False, 2)
        #container.set_border_width(2)
        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        container.pack_start(self.image, expand=False, fill=False)
        container.pack_start(self.label, expand=False, fill=False)
        alignment.add(container)
        self.add(alignment)
        self._set_off()
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
        if self.open_only:
            self.set_sensitive(False)
        else:
            if not self.action_label:
                self.label.set_text(self.label_text)
            else:
                self.label.set_text("Close")
        self.image.set_from_stock('gtk-yes', gtk.ICON_SIZE_SMALL_TOOLBAR)
    
    def _set_off(self):
        self.set_sensitive(True)
        if not self.action_label:
            self.label.set_text(self.label_text)
        else:
            self.label.set_text("Open")
        self.image.set_from_stock('gtk-no', gtk.ICON_SIZE_SMALL_TOOLBAR)

class ScriptButton(gtk.Button):
    def __init__(self, script, label, confirm=False, message=""):
        gtk.Button.__init__(self)
        self.script = script
        self.confirm = confirm
        self.warning_text = message
        alignment = gtk.Alignment(0.5,0.5,0.0,0.0)
        container = gtk.HBox(False, 2)

        self.label_text = label
        self.image = gtk.Image()
        self.label = gtk.Label(label)
        self.image.set_alignment(0.5, 0.5)
        self.label.set_alignment(0.5, 0.5)
        container.pack_start(self.image, expand=False, fill=False)
        container.pack_start(self.label, expand=False, fill=False)
        alignment.add(container)
        self.add(alignment)
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
        self.tooltip = gtk.Tooltips()
        self.tooltip.set_tip(self, self.script.description)
        self._set_off()
        self.set_property('can-focus', False)
        self.script.connect('done', self._on_state_change)
        self.script.connect('error', self._on_state_change)
        self.connect('clicked', self._on_clicked)
            
    def _on_clicked(self, widget):
        if self.confirm and not self.script.is_active():
            response = warning(self.script.description, self.warning_text, buttons=(('Cancel', gtk.BUTTONS_CANCEL), ('Proceed', gtk.BUTTONS_OK)))
            if response == gtk.BUTTONS_OK:
                self.script.start()
                self._set_on()  
        elif not self.script.is_active():
            self.script.start()
            self._set_on()  
        
    def _on_state_change(self, obj, value=None):
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


class TextStatusDisplay(gtk.Label):
    def __init__(self, device, text_map={}, sig='changed'):
        self.text_map = text_map
        gtk.Label.__init__(self,'')
        self.device = device
        self.set_use_markup(True)
        self.device.connect(sig, self._on_signal)
                    
    def _on_signal(self, obj, state):
        self.set_markup(self.text_map.get(state, state))
        return True

    

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
    
    
    def set_busy(self, busy):
        if busy:
            self.busy_state = True
            if self.progress_id is None:
                self.progress_id = gobject.timeout_add(100,  self._progress_timeout)
            self.pulse()
        else:
            self.busy_state = False
            if self.progress_id is not None:
                gobject.source_remove(self.progress_id)
            self.set_fraction(0.0)

    def get_busy(self):
        return self.busy_state

    def _progress_timeout(self):
        self.pulse()
        return True
     
    def busy_text(self, text):
        self.set_busy(True)
        self.set_text(text)
    
    def idle_text(self, text, fraction=0.0):
        self.set_busy(False)
        self.set_fraction(fraction)
        self.set_text(text)
    
    def set_complete(self, complete, text=''):
        self.set_busy(False)
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
        self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_out.png'))
        
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
            }
        for k,v in tbl_data.items():
            lb = ActiveLabel(v[1])
            lb.set_alignment(0.5, 0.5)
            self.status_table.attach(lb, 1, 2, v[0], v[0]+1)

        self.duration_entry.set_alignment(0.5)
        self.start_anneal_btn.connect('clicked', self._start_anneal)
        self.stop_anneal_btn.connect('clicked', self._stop_anneal)
        self._restore_anneal_id = None
        self._progress_id = None
        self._annealed_time = 0
        self.stop_anneal_btn.set_sensitive(False)
        self.retract_btn.connect('clicked', lambda x: self.cryojet.nozzle.open())
        self.restore_btn.connect('clicked', lambda x: self.cryojet.nozzle.close())
        self.cryojet.nozzle.connect('changed', self._on_nozzle_change)
        
    
    def __getattr__(self, key):
        try:
            return super(CryojetWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
                
    def _on_level(self, obj, val):
        self.level_gauge.value = val/10.0
        return False
    
    def _on_nozzle_change(self, obj, state):
        if not state:
            self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_in.png'))
        else:
            self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_out.png'))
            
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
            self.start_anneal_btn.set_sensitive(False)
            self.stop_anneal_btn.set_sensitive(True)
            self._annealed_time = 0
            self.cryojet.stop_flow()
            dur = max(0.0, (duration-0.5*1000))
            self._restore_anneal_id = gobject.timeout_add(duration*1000, self._stop_anneal)
            self._progress_id = gobject.timeout_add(1000, self._update_progress, duration)
            
    def _stop_anneal(self, obj=None):
        self.cryojet.resume_flow()
        self.start_anneal_btn.set_sensitive(True)
        self.stop_anneal_btn.set_sensitive(False)
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

from plotter import Plotter

class HCWidget(gtk.Frame):
    def __init__(self, hc):
        gtk.Frame.__init__(self, '')
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.hc = hc
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'hc_widget.glade'), 
                                  'hc_widget')
        self.hc_widget = self._xml.get_widget('hc_widget')
        self.add(self.hc_widget)
        
        self.temp_btn.connect('clicked', self.on_view_temp)
        self.dropsize_btn.connect('clicked', self.on_view_dropsize)
        self.plotter = Plotter(xformat='%g')
        self.hc_plot.add(self.plotter)

        self.temp_plot = True
        self.drop_plot = False
        self.follow_data()

        self.start_time = time.time()
        self.temp_btn.set_active(True)
        
    def __getattr__(self, key):
        try:
            return super(CryojetWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
                
    def follow_data(self):
        gobject.timeout_add(1000, self._follow_data)
        return True
    
    def _follow_data(self):
        print self.temp_plot, self.drop_plot 
        if self.temp_plot:
            print "adding a point"
            self.plotter.add_point(time.time()-self.start_time, self.hc.temperature.get())
        elif self.drop_plot:
            self.plotter.add_point(time.time()-self.start_time, self.hc.drop_size.get())
        return True  
        
    def on_view_temp(self, widget):
        if widget.get_active():
            self.temp_plot = True
            self.dropsize_btn.set_active(False)
            self.plotter.clear()
            self.plotter.add_line([time.time()-self.start_time], [self.hc.temperature.get()], '-')
        else:
            self.temp_plot = False
        
    def on_view_dropsize(self, widget):
        if widget.get_active():
            self.drop_plot = True
            self.temp_btn.set_active(False)
            self.plotter.clear()
            self.plotter.add_line([time.time()-self.start_time], [self.hc.drop_size.get()], '-')
        else:
            self.drop_plot = False
                
    def _refresh_temp(self, widget):
        print self.temp_btn.toggled()
        self.temp_plot = True
        self.drop_plot = False
                
    def _refresh_dropsize(self, widget):
        print self.hc_plot

    def make_plot(self):
        self.plotter.clear()
        self.plotter.add_line([5, 5], [5, 3], '-')
        self.plotter.set_labels(x_label='Time', y1_label='Drop Size (um)')
        new_axis = self.plotter.add_axis(label="Relative Humidity")
        self.plotter.redraw()
