
from mxdc.utils.misc import lighten_color
from diagnostics import MSG_COLORS, MSG_ICONS
from dialogs import warning
from gauge import Gauge
from mxdc.utils import gui
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GdkPixbuf
from gi.repository import Gdk
import os
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class ActiveHScale(Gtk.HScale):
    def __init__( self, context, min_val=0.0, max_val=100.0):
        super(ActiveHScale, self).__init__()
        self.context = context
        self.set_value_pos(Gtk.PositionType.RIGHT)
        self.set_digits(1)
        self.set_range(min_val, max_val)
        self.set_adjustment(Gtk.Adjustment(0.0, min_val, max_val, (max_val-min_val)/100.0, 0, 0))
        #self.set_update_policy(Gtk.UPDATE_CONTINUOUS)
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
        
class ActiveLabel(Gtk.Label):
    def __init__( self, context, fmt="%s", show_units=True, rng=None):
        super(ActiveLabel, self).__init__('')

        self.set_alignment(0.5,0.5)
        self.format = fmt
        self.context = context
        self.context.connect('changed', self._on_value_change )
        self.range = rng
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
        #print alarm, severity
        
class ActiveEntry(Gtk.VBox):
    #_border = Gtk.Border(3,3,4,4)
    def __init__( self, device, label=None,  fmt="%g",  width=10):
        super(ActiveEntry, self).__init__(label)
        self._sizegroup_h = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)
        self._sizegroup_v = Gtk.SizeGroup(Gtk.SizeGroupMode.VERTICAL)
        # create gui layout
        
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/active_entry'), 
                                  'active_entry')
        
        self._active_entry = self._xml.get_widget('active_entry')
        self._fbk_label = self._xml.get_widget('fbk_label')
        
        self._entry = self._xml.get_widget('entry')
        self._action_btn = self._xml.get_widget('action_btn')
        self._action_icon = self._xml.get_widget('action_icon')
        self._label = self._xml.get_widget('label')
        #font_desc = Pango.FontDescription()

        self._sizegroup_h.add_widget(self._entry)
        self._sizegroup_h.add_widget(self._fbk_label)
        self._sizegroup_v.add_widget(self._entry)
        self._sizegroup_v.add_widget(self._fbk_label)

        #self._entry.connect('event', self._on_entry_clicked)
        #self._sizegroup_v.add_widget(self._action_btn)

        #font_desc.set_family('#monospace')
        #self._fbk_label.modify_font(font_desc)


        self.pack_start(self._active_entry, True, True, 0)
        
        self._fbk_label.set_alignment(1, 0.5)
        #self._entry.set_inner_border(self._border)
        
        self._entry.set_width_chars(1)
        self._entry.set_alignment(1)
        
        # signals and parameters
        self.device = device
        self.device.connect('changed', self._on_value_changed)
        self.device.connect('active', self._on_active_changed)
        self.device.connect('health', self._on_health_changed)
        self._action_btn.connect('clicked', self._on_activate)
        self._entry.connect('activate', self._on_activate)
        
        self._first_change = True
        self._last_signal = 0
        self.running = False
        self.action_active = True
        self.width = width
        self.number_format = fmt
        self.format = self.number_format
        
        if label is None:
            label = self.device.name
        
        if self.device.units != "":
            label = '%s (%s)' % (label, self.device.units)
        self._label.set_markup("<span size='small'><b>%s</b></span>" % (label,))
        self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#000088"))

    def _on_entry_clicked(self, widget, event, data=None):
        if event.type == Gdk.BUTTON_RELEASE:
            widget.select_region(0, -1)
          
    def set_feedback(self, val):
        text = self.number_format % val
        if len(text) > self.width:
            text = "##.##"
        self._fbk_label.set_markup('%7s ' % (text,))

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
    
    def _on_health_changed(self, obj, health):
        state, _ = health
        
        if state == 0:
            self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#000066"))
            self._action_icon.set_from_stock('gtk-apply', Gtk.IconSize.MENU)
            self._set_active(True)
        else:           
            if (state | 16) == state:
                self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#333366"))
            else:                
                self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#660000"))
                self._action_icon.set_from_stock('gtk-dialog-warning', Gtk.IconSize.MENU)
            self._set_active(False)           

    def _on_value_changed(self, obj, val):
        if time.time() - self._last_signal > 0.1:
            self.set_feedback(val)
            self._last_signal = time.time()
        if self._first_change:
            #self.set_target(val)
            self._first_change = False
        return True
        
    def _on_activate(self, obj):
        if self.action_active:
            if self.running:
                self.stop()
            else:
                self.apply()
        return True
    
    def _set_active(self, state):
        self.action_active = state
        if state:
            self._entry.set_sensitive(True)
            #self._action_btn.set_sensitive(True)
        else:
            self._entry.set_sensitive(False)
            #self._action_btn.set_sensitive(False)

    def _on_active_changed(self, obj, state):
        self._set_active(state)
            
                    
    
            
class MotorEntry(ActiveEntry):
    def __init__(self, mtr, label=None, fmt="%0.3f", width=8):
        super(MotorEntry, self).__init__(mtr, label=label, fmt=fmt, width=width)
        self._set_active(False)
        self.device.connect('busy', self._on_motion_changed)
        self.device.connect('target-changed', self._on_target_changed)
        
        self._animation = GdkPixbuf.PixbufAnimation.new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
           
    def stop(self):
        self.device.stop()
        self._action_icon.set_from_stock('gtk-apply', Gtk.IconSize.MENU)
             
    
    def _on_motion_changed(self, obj, motion):
        if motion:
            self.running = True
            self._action_icon.set_from_animation(self._animation)
            self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#0000ff"))
        else:
            self.running = False
            #self.set_target(self.device.get_position())
            self._action_icon.set_from_stock('gtk-apply',Gtk.IconSize.MENU)
            self._fbk_label.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#000066"))
        self.set_feedback(self.device.get_position())
        return True

    def _on_target_changed(self, obj, targets):
        self.set_target(targets[-1])
        return True
   


class ShutterButton(Gtk.ToggleButton):
    def __init__(self, shutter, label, open_only=False, action_label=False):
        super(ShutterButton, self).__init__()
        self.shutter = shutter
        self.open_only = open_only
        self.action_label = action_label
        container = Gtk.HBox(False, 2)

        self.label_text = label
        self.image = Gtk.Image()
        self.label = Gtk.Label(label=label)
        self.image.set_alignment(0.5, 0.5)
        self.image.set_padding(3,0)
        self.label.set_alignment(0.0, 0.5)
        self.label.set_padding(3,0)
        
        container.pack_start(self.image, False, False, 0)
        container.pack_start(self.label, True, True, 0)
        self.add(container)
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
        self.image.set_from_stock('gtk-yes', Gtk.IconSize.SMALL_TOOLBAR)
    
    def _set_off(self):
        self.set_sensitive(True)
        if not self.action_label:
            self.label.set_text(self.label_text)
        else:
            self.label.set_text("Open")
        self.image.set_from_stock('gtk-no', Gtk.IconSize.SMALL_TOOLBAR)

class ScriptButton(Gtk.Button):
    def __init__(self, script, label, confirm=False, message=""):
        super(ScriptButton, self).__init__()
        self.script = script
        self.confirm = confirm
        self.warning_text = message
        self._animation = GdkPixbuf.PixbufAnimation.new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
        container = Gtk.HBox(False, 2)

        self.label_text = label
        self.image = Gtk.Image()
        self.label = Gtk.Label(label=label)
        self.image.set_alignment(0.5, 0.5)
        self.image.set_padding(3,0)
        self.label.set_alignment(0.0, 0.5)
        self.label.set_padding(3,0)
        container.pack_start(self.image, False, False, 0)
        container.pack_end(self.label, True, True, 0)
        self.add(container)
        self.set_tooltip_text(self.script.description)
        self._set_off()
        self.set_property('can-focus', False)
        self.script.connect('done', lambda x,y: self._set_off())
        self.script.connect('error', lambda x: self._set_err())
        self.script.connect('started',lambda x: self._set_on())
        self.script.connect('enabled', self._on_enabled)
        self.connect('clicked', self._on_clicked)
            
    def _on_clicked(self, widget):
        if self.confirm and not self.script.is_active():
            response = warning(self.script.description, self.warning_text, buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK)))
            if response == Gtk.ButtonsType.OK:
                self.script.start()
                self._set_on()  
        elif not self.script.is_active():
            self.script.start()
                    
    def _set_on(self):
        self.image.set_from_animation(self._animation)
        self.label.set_sensitive(False)
    
    def _set_off(self):
        self.image.set_from_stock('gtk-execute', Gtk.IconSize.SMALL_TOOLBAR)
        self.label.set_sensitive(True)

    def _set_err(self):
        self.image.set_from_stock('gtk-warning', Gtk.IconSize.SMALL_TOOLBAR)
        self.label.set_sensitive(True)

    def _on_enabled(self, obj, state):
        if state:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
                    
class StatusBox(Gtk.EventBox):
    COLOR_MAP = {
        'blue':'#6495ED',
        'orange': '#DAA520',
        'red': '#CD5C5C',
        'green': '#8cd278',
        'gray' : '#708090',
        'violet': '#9400D3',
    }

    def __init__(self, device, color_map={}, value_map={}, signal="changed", markup="<small><b>%s</b></small>", background=False):
        super(StatusBox, self).__init__()
        hbox = Gtk.HBox()
        self.state_map = color_map
        self.value_map = value_map
        self.markup = markup
        self.background = background
        self.label = Gtk.Label(label='')
        self.label.set_alignment(0.5, 0.5)
        self.device = device
        self.device.connect(signal, self._on_signal)
        hbox.pack_start(self.label, True, False, 0)
        self.add(hbox)
        self.show_all()
                
    def _on_signal(self, obj, state):
        self.label.set_markup(self.markup % self.value_map.get(state, state))
        color = self.COLOR_MAP.get(self.state_map.get(state, 'gray'), '#708090')
        if self.background:
            fg_color = lighten_color(color, step=153)
            self.label.modify_fg(Gtk.StateType.NORMAL,Gdk.color_parse(fg_color))
            self.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse(color))
        else:
            self.label.modify_fg(Gtk.StateType.NORMAL,Gdk.color_parse(color))
        return True


class TextStatusDisplay(Gtk.Label):
    def __init__(self, device, text_map={}, sig='changed'):
        self.text_map = text_map
        super(TextStatusDisplay, self).__init__('')
        self.device = device
        self.set_use_markup(True)
        self.device.connect(sig, self._on_signal)
                    
    def _on_signal(self, obj, state):
        self.set_markup(self.text_map.get(state, state))
        self.set_alignment(0.5, 0.5)
        return True

class HealthDisplay(Gtk.HBox):
    def __init__(self, device, label='', icon_map=MSG_ICONS, color_map=MSG_COLORS, sig='health'):
        super(HealthDisplay, self).__init__(False, 0)
        
        self.nm = Gtk.Label(label='')
        self.nm.set_alignment(0.1, 0.5)
        self.nm.set_markup('<small><b>%s</b></small>' % label)
        
        self.status = Gtk.Label(label='')
        self.status.set_alignment(0.95, 0.5)
        self.device = device
        self.device.connect(sig, self._on_signal)

        self.icon = Gtk.Image()
        self.icon.set_alignment(0.1,0.5)
        self.icon_map = icon_map
        self.color_map = color_map
        self.pack_start(self.icon, False, False, 0)
        self.pack_start(self.nm, True, True, 0)
        self.pack_start(self.status, True, True, 0)
        
    def _on_signal(self, obj, status):
        state = status[0]
        text = status[1] or 'Connected and Ready'
        self.status.set_markup('<small><span color="%s"><i>%s</i></span></small>' 
                               % (self.color_map.get(state, '#9a2b2b'), text))
        self.icon.set_from_stock(self.icon_map.get(state, 'mxdc-hcane'), Gtk.IconSize.MENU)
        return True
    
class StatusDisplay(Gtk.HBox):
    def __init__(self, icon_list, message):
        super(StatusDisplay, self).__init__(False, 0)
        self.message = message
        self.icon_list = icon_list
        self.image = Gtk.Image()
        self.label = Gtk.Label()
        self.pack_start(self.image, False, False, 0)
        self.pack_start(self.label, True, True, 0)
                                        
    def set_state(self, val=None, message=None):
        if val is not None:
            if len(self.icon_list) > val > 0:
                self.image.set_from_stock(self.icon_list[val], Gtk.IconSize.MENU)
        if message is not None:
            self.message = message
            self.label.set_markup(message)
        
class ActiveProgressBar(Gtk.ProgressBar):
    def __init__(self):
        super(ActiveProgressBar, self).__init__()    
        self.set_fraction(0.0)
        self.set_text('0.0%')
        self.progress_id = None
        self.busy_state = False
    
    
    def set_busy(self, busy):
        if busy:
            if not self.busy_state:
                self.busy_state = True
                GObject.timeout_add(100,  self._progress_timeout)
            self.pulse()
        else:
            self.busy_state = False

    def get_busy(self):
        return self.busy_state

    def _progress_timeout(self):
        if self.busy_state:
            self.pulse()
        return self.busy_state
     
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
    
        
           
class CryojetWidget(Gtk.Alignment):
    def __init__(self, cryojet):
        super(CryojetWidget, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self.cryojet = cryojet
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'cryo_widget'), 
                                  'cryo_widget')
        self.cryo_widget = self._xml.get_widget('cryo_widget')
        self.add(self.cryo_widget)
        self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_out.png'))
        
        # layout the gauge section
        self.level_gauge = Gauge(0, 100, 6, 4)
        self.level_gauge.set_property('label',"LN%s Level" % (u"\u2082"))
        self.level_gauge.set_property('units',"[%]")
        self.level_gauge.set_property('low', 20.0)
        self.level_frame.add(self.level_gauge)
        self.cryojet.level.connect('changed', self._on_level)
        
        # Status section
        tbl_data = {
            'temp': (0, self.cryojet.temperature),
            'smpl': (1, self.cryojet.sample_flow),
            'shld': (2, self.cryojet.shield_flow),
            }
        for v in tbl_data.values():
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
            
        response = warning(msg1, msg2, buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Anneal', Gtk.ButtonsType.OK)))
        if response == Gtk.ButtonsType.OK:
            self.start_anneal_btn.set_sensitive(False)
            self.stop_anneal_btn.set_sensitive(True)
            self._annealed_time = 0
            self.cryojet.stop_flow()
            #dur = max(0.0, (duration-0.5*1000))
            self._restore_anneal_id = GObject.timeout_add(int(duration*1000), self._stop_anneal)
            self._progress_id = GObject.timeout_add(1000, self._update_progress, duration)
            
    def _stop_anneal(self, obj=None):
        self.cryojet.resume_flow()
        self.start_anneal_btn.set_sensitive(True)
        self.stop_anneal_btn.set_sensitive(False)
        self.anneal_prog.set_fraction(0.0)
        self.anneal_prog.set_text('')
        if self._restore_anneal_id:
            GObject.source_remove(self._restore_anneal_id)
            self._restore_anneal_id = None
        if self._progress_id:
            GObject.source_remove(self._progress_id)
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

