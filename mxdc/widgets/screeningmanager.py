import os
import time, datetime
import gtk
import gobject
import pango
import logging

from twisted.python.components import globalRegistry
from mxdc.widgets.samplelist import SampleList
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets import dialogs
from mxdc.widgets.ptzviewer import AxisViewer
from bcm.beamline.mx import IBeamline
from bcm.engine.interfaces import IDataCollector
from bcm.utils.runlists import determine_skip, summarize_frame_set
from bcm.utils import automounter
from bcm.utils import lims_tools
from bcm.engine.diffraction import Screener, DataCollector
from bcm.engine.rastering import RasterCollector
from mxdc.widgets.rasterwidget import RasterWidget
from mxdc.widgets.textviewer import TextViewer, GUIHandler
from mxdc.widgets.dialogs import warning, MyDialog
from mxdc.utils import config, gui
from bcm.engine.scripting import get_scripts

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

TASKLET_NAME_MAP = {
    Screener.TASK_MOUNT : 'Mount Crystal',
    Screener.TASK_ALIGN : 'Center Crystal',
    Screener.TASK_PAUSE : 'Pause',
    Screener.TASK_COLLECT : 'Collect Frames',
    Screener.TASK_ANALYSE : 'Request Analysis',
    Screener.TASK_DISMOUNT : 'Dismount Last',
}

PAUSE_MSGS = { 
    Screener.PAUSE_ALIGN: 'Screening paused automatically, due to centering error ',
    Screener.PAUSE_MOUNT: 'Screening stopped, because automounting failed: ',
    Screener.PAUSE_UNRELIABLE: 'Screening paused automatically, due to unreliable auto-centering ',
    Screener.PAUSE_TASK: 'Screening paused automatically, as requested, after completing ',
    Screener.PAUSE_BEAM: 'Beam not Available. Screening has been paused and will automatically resume once the beam becomes available.  Intervene to manually resume screening.' 
}

(
    QUEUE_COLUMN_STATUS,
    QUEUE_COLUMN_ID,
    QUEUE_COLUMN_NAME,
    QUEUE_COLUMN_TASK,
) = range(4)

SCREEN_CONFIG_FILE = 'screen_config.json'

class Tasklet(object):
    def __init__(self, task_type, **kwargs):
        self.options = {}
        self.name = TASKLET_NAME_MAP[task_type]
        self.task_type = task_type
        self.configure(**kwargs)
    
    def configure(self, **kwargs):
            self.options.update(kwargs)

    def __repr__(self):
        if self.task_type == Screener.TASK_COLLECT:
            _info = 'Collecting %s' % (self.options.get('frame_set'))
        elif self.task_type == Screener.TASK_DISMOUNT:
            _info = self.name
        else:
            _info = '%s: %s' % (self.name, self.options['sample']['name'])
        return _info
    
    def __getitem__(self, key):
        return self.options[key]

class ScreenManager(gtk.Frame):
    __gsignals__ = {
        'new-datasets': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }

    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'screening_widget'), 
                                  'screening_widget')
        self.samples_data = []
        self._create_widgets()
        self.screen_runner = Screener()
        
        self._screening = False
        self._screening_paused = False
        self.screen_runner.connect('progress', self._on_progress)
        self.screen_runner.connect('stopped', self._on_stop)
        self.screen_runner.connect('paused', self._on_pause)
        self.screen_runner.connect('started', self._on_start)
        self.screen_runner.connect('done', self._on_complete)
        self.screen_runner.connect('sync', self._on_sync)
        self.screen_runner.connect('new-datasets', self._on_new_datasets)
        
        self.beamline = globalRegistry.lookup([], IBeamline)
        self._beam_up = False
        self._intervening = False
        self._last_sample = None
        self.scripts = get_scripts()

        # extra widgets
        self._full_state = []
        

    def __getattr__(self, key):
        try:
            return super(ScreenManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_new_datasets(self, datasets):
        pass

    def _create_widgets(self):
     
        self.sample_list = SampleList()
        self.beamline = globalRegistry.lookup([], IBeamline)

        self.screen_manager = self._xml.get_widget('screening_widget')
        self.message_log = TextViewer(self.msg_txt)
        self.message_log.set_prefix('- ')
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                           'data/busy.gif'))
        pango_font = pango.FontDescription('sans 8')
        self.lbl_current.modify_font(pango_font)
        self.lbl_next.modify_font(pango_font)
        self.lbl_sync.modify_font(pango_font)

        self.status_lbl.modify_font(pango_font)
        self.lbl_port.modify_font(pango_font)
        self.lbl_barcode.modify_font(pango_font)
        self._set_throbber('idle')

        #signals
        self.clear_btn.connect('clicked', self._on_queue_clear)
        self.apply_btn.connect('clicked', self._on_sequence_apply)
        self.reset_btn.connect('clicked', self._on_sequence_reset)
        self.select_all_btn.connect('clicked', lambda x: self.sample_list.select_all(True) )
        self.deselect_all_btn.connect('clicked', lambda x: self.sample_list.select_all(False) )
        self.refresh_btn.connect('clicked', lambda x: self.refresh_samples())
        self.start_btn.connect('clicked', self._on_activate)
        self.stop_btn.connect('clicked', self._on_stop_btn_clicked)
        self.start_btn.set_label('mxdc-start')
        self.stop_btn.set_label('mxdc-stop')
        
        self.automounter = self.beamline.automounter
        self.automounter.connect('message', self._on_automounter_state)
        self.automounter.connect('mounted', self._on_sample_mounted)
        self.automounter.connect('status', self._on_automounter_state)
        self.automounter.connect('busy', self._on_automounter_state)
        self.automounter.connect('health', self._on_automounter_state)   
        self.automounter.connect('active', self._on_automounter_state)
        self.automounter.connect('enabled', self._on_automounter_state)
             
        self.sample_box.pack_start(self.sample_list, expand=True, fill=True)

        # video        
        self.sample_viewer = SampleViewer()
        self.image_viewer = ImageViewer()
        self.image_viewer.set_collect_mode(True)
        self.image_viewer.set_shadow_type(gtk.SHADOW_NONE)
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.video_book.append_page(self.sample_viewer, tab_label=gtk.Label('Sample Camera'))
        self.video_book.append_page(self.hutch_viewer, tab_label=gtk.Label('Hutch Camera'))    
        self.video_book.connect('realize', lambda x: self.video_book.set_current_page(0))
                
        #create a data collector and attach it to diffraction viewer
        self.data_collector = DataCollector()
        self.data_collector.connect('new-image', self._on_diffraction_image)
        globalRegistry.register([], IDataCollector, 'mxdc.screening', self.data_collector)
        self.screen_ntbk.append_page(self.image_viewer, tab_label=gui.make_icon_label('Diffraction Viewer'))
        self.screen_ntbk.connect('switch-page', self._on_page_switch)

        # raster screening
        self.raster_collector = RasterCollector()
        self.raster_collector.connect('new-image', self._on_diffraction_image)
        self.raster_widget = RasterWidget()
        self.raster_widget.link_viewer(self.sample_viewer)
        self.raster_widget.link_collector(self.raster_collector)
        self.raster_widget.connect('show-raster', self._on_show_raster)
        self.raster_widget.connect('show-image', self._on_diffraction_image)
        self.activity_ntbk.append_page(self.raster_widget, tab_label=gui.make_tab_label('Raster Screening'))
        
        # Task Configuration
        self.TaskList = []
        self.default_tasks = [ 
                  (Screener.TASK_MOUNT, {'default': True, 'locked': False}),
                  (Screener.TASK_ALIGN, {'default': False, 'locked': False}),
                  (Screener.TASK_PAUSE, {'default': True, 'locked': False}), # use this line for collect labels
                  (Screener.TASK_COLLECT, {'angle': 0.0, 'default': True, 'locked': False}),
                  (Screener.TASK_COLLECT, {'angle': 45.0, 'default': True, 'locked': False}),
                  (Screener.TASK_COLLECT, {'angle': 90.0, 'default': True, 'locked': False}),
                  (Screener.TASK_ANALYSE, {'default': True, 'locked': False}),
                  (Screener.TASK_PAUSE, {'default': False, 'locked': False}), ]
        self._settings_sg = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        
        # connect signals for collect parameters
        self.delta_entry.connect('activate', self._on_entry_changed, None, (0.2, 90.0, 1.0))
        self.delta_entry.connect('focus-out-event', self._on_entry_changed, (0.2, 90.0, 1.0))
        self.distance_entry.connect('activate', self._on_entry_changed, None, (100, 1000.0, 300.0))
        self.distance_entry.connect('focus-out-event', self._on_entry_changed, (100, 1000.0, 300.0))
        self.time_entry.connect('activate', self._on_entry_changed, None, (0.1, 360.0, self.beamline.config['default_exposure']))
        self.time_entry.connect('focus-out-event', self._on_entry_changed, (0.1, 360.0, self.beamline.config['default_exposure']))
        self.beamline.energy.connect('changed', lambda obj, val: self.energy_entry.set_text('%0.4f' % val))
        
        for pos, tasklet in enumerate(self.default_tasks):
            key, options = tasklet
            options.update(enabled=options['default'])
            t = Tasklet(key, **options)
            tbtn = gtk.CheckButton(t.name)
            tbtn.connect('toggled', self._on_task_toggle, t)
            
            tbtn.set_active(options['default'])
            tbtn.set_sensitive(not(options['locked']))

            if key == Screener.TASK_COLLECT:
                ctable = self._get_collect_setup(t)
                ctable.attach(tbtn, 0, 3, 0, 1)
                self.task_config_box.pack_start(ctable, expand=True, fill=True)
                
            elif pos == 2:
                ctable = self._get_collect_labels()
                ctable.attach(tbtn, 0, 3, 0, 1)
                self.task_config_box.pack_start(ctable, expand=True, fill=True)
            else:
                ctable = gtk.Table(1, 7, True)
                ctable.attach(tbtn, 0, 3, 0, 1)
                ctable.attach(gtk.Label(''), 4, 6, 0, 1)
                self.task_config_box.pack_start(ctable, expand=True, fill=True)
                
            self._settings_sg.add_widget(tbtn)
            self.TaskList.append((t, tbtn))
        
        # Run List
        self.listmodel = gtk.ListStore(
            gobject.TYPE_INT,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT,
        )
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self._add_columns()
        self.task_queue_window.add(self.listview)    


        log_handler = GUIHandler(self.message_log)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(message)s')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        self.add(self.screen_manager)
        self.connect('realize', lambda x: self._load_config())
        self.show_all()
        
        #prepare pixbufs for status icons
        self._wait_img = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR,'tiny-wait.png'))
        self._ready_img = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR,'tiny-ready.png'))
        self._error_img = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR, 'tiny-error.png'))
        self._skip_img = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR,'tiny-skip.png'))
        self._info_img = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR,'tiny-info.png'))


    def _set_throbber(self, st):
        if st == 'error':
            self.throbber.set_from_stock('robot-error', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'standby':
            self.throbber.set_from_stock('robot-standby', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'warning':
            self.throbber.set_from_stock('robot-warning', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'busy':
            self.throbber.set_from_animation(self._animation)
        elif st == 'idle':
            self.throbber.set_from_stock('robot-idle', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'setup':
            self.throbber.set_from_stock('robot-setup', gtk.ICON_SIZE_LARGE_TOOLBAR)

            
    def _on_automounter_state(self, obj, val):
        code, h_msg = self.automounter.health_state
        status = self.automounter.status_state
        message = self.automounter.message_state
        busy = self.automounter.busy_state
        enabled = self.automounter.enabled_state
        active = self.automounter.active_state
        
        # Do nothing if the state has not really changed
        _new_state = [code, h_msg, status, message, busy, enabled, active]
        if _new_state == self._full_state:
            return
        else:
            self._full_state = _new_state
            
        if code == 16: 
            self._set_throbber('warning')
        elif code >= 2:
            self._set_throbber('error')
        else:
            if not busy:
                self._set_throbber(status)
            else:
                self._set_throbber('busy') 
        if message.strip() == "":
            message = h_msg

        message = "<span color='blue'>%s</span>" % message.strip()
        if h_msg.strip() != '':
            self.message_log.add_text(h_msg)
        self.status_lbl.set_markup(message) 
        
    
    def _on_sample_mounted(self, obj, info):
        if info is None: # dismounting
            self.lbl_port.set_markup('')
            self.lbl_barcode.set_markup('')
        else:   
            port, barcode = info
            if port is not None:
                self.lbl_port.set_markup("<span color='blue'>%s</span>" % port)
                self.lbl_barcode.set_markup("<span color='blue'>%s</span>" % barcode)
            else:
                self.lbl_port.set_markup('')
                self.lbl_barcode.set_markup('')
    

    def _on_sync(self, obj, st, str):
        if st:
            self.lbl_sync.set_markup('<span color="#009900">Barcode match</span>')
        else:
            self.lbl_sync.set_markup('<span color="#990000">Barcode mismatch</span>')
            self.message_log.add_text('sync: %s' % str)


    def _on_new_datasets(self, obj, datasets):
        datasets = lims_tools.upload_data(self.beamline, datasets)
        self.emit('new-datasets', datasets)

               
        
    def refresh_samples(self):
        self.sample_list.clear()
        for sample in self.samples_data:
            sample['state'] = self.beamline.automounter.get_port_state(sample.get('port'))
        self.sample_list.load_data(self.samples_data)        

    def add_samples(self, samples):
        self.samples_data = samples
        self.refresh_samples()
            
    def get_task_list(self):
        model = self.listview.get_model()
        iter = model.get_iter_first()
        items = []
        while iter:
            tsk = model.get_value(iter, QUEUE_COLUMN_TASK)
            items.append(tsk)
            iter = model.iter_next(iter)
        return items
    
    def _get_collect_setup(self, task):
        _xml2 = gui.GUIFile(os.path.join(DATA_DIR, 'screening_widget'), 
                          'collect_settings')
        tbl = _xml2.get_widget('collect_settings')
        for key in ['angle','frames']:
            en = _xml2.get_widget('%s_entry' % key)
            if task.options.get(key,None):
                en.set_text('%s' % task.options.get(key))
              
            if key == 'frames':
                en.default_value = int(en.get_text())
            else:
                en.default_value = float(en.get_text())
            task.options[key] = en.default_value
            en.connect('activate', self._on_settings_changed, None, task, key)
            en.connect('focus-out-event', self._on_settings_changed, task, key)
        return tbl

    def _get_collect_labels(self):
        _xml2 = gui.GUIFile(os.path.join(DATA_DIR, 'screening_widget'), 
                          'collect_labels')
        tbl = _xml2.get_widget('collect_labels')
        return tbl
    
    def _on_settings_changed(self, obj, event, task, key):
        try:
            val = float( obj.get_text() )
        except:
            if key == 'frames':
                obj.set_text( '%d' % obj.default_value )
            else:
                obj.set_text( '%0.1f' % obj.default_value )
            val = obj.default_value
        task.options[key] = val
    
    def _on_entry_changed(self, obj, event, data):
        min_val, max_val, default = data
        try:
            val = float( obj.get_text() )
            val = min(max_val, max(min_val, val))
        except:
            val = default
        obj.set_text( '%0.2f' % val )
            
        
       
    def _add_item(self, item):
        iter = self.listmodel.append()
        sample = item['task'].options.get('sample', {}) # dismount does not have a sample
        self.listmodel.set(iter, 
            QUEUE_COLUMN_STATUS, item.get('status', Screener.TASK_STATE_PENDING), 
            QUEUE_COLUMN_ID, sample.get('name', '[LAST]'), # use [LAST] as sample name
            QUEUE_COLUMN_NAME, item['task'].name,
            QUEUE_COLUMN_TASK, item['task'],
        )
        self.start_btn.set_sensitive(True)
        
    def _done_color(self, column, renderer, model, iter):
        status = model.get_value(iter, QUEUE_COLUMN_STATUS)
        _state_colors = {
            Screener.TASK_STATE_PENDING : None,
            Screener.TASK_STATE_RUNNING : '#990099',
            Screener.TASK_STATE_DONE : '#006600',
            Screener.TASK_STATE_ERROR : '#990000',
            Screener.TASK_STATE_SKIPPED : '#777777',
            }
        renderer.set_property("foreground", _state_colors.get(status))
        
    def _done_pixbuf(self, column, renderer, model, iter):
        value = model.get_value(iter, QUEUE_COLUMN_STATUS)
        if value == Screener.TASK_STATE_PENDING:
            renderer.set_property('pixbuf', None)
        elif value == Screener.TASK_STATE_RUNNING:
            renderer.set_property('pixbuf', self._wait_img)
        elif value == Screener.TASK_STATE_DONE:
            renderer.set_property('pixbuf', self._ready_img)
        elif value == Screener.TASK_STATE_ERROR:
            renderer.set_property('pixbuf', self._error_img)
        elif value == Screener.TASK_STATE_SKIPPED:
            renderer.set_property('pixbuf', self._skip_img)
        else:
            renderer.set_property('pixbuf', None)

    def _add_columns(self):
        # Status Column
        renderer = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn('', renderer)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)
        column.set_cell_data_func(renderer, self._done_pixbuf)
        self.listview.append_column(column)

        # Name Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Crystal', renderer, text=QUEUE_COLUMN_ID)
        column.set_cell_data_func(renderer, self._done_color)
        self.listview.append_column(column)

        # Task Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Task', renderer, text=QUEUE_COLUMN_NAME)
        column.set_cell_data_func(renderer, self._done_color)
        self.listview.append_column(column)
    
    def _save_config(self):
        data = {
            "directory": self.folder_btn.get_filename(),
            "delta": float(self.delta_entry.get_text()),
            "time": float(self.time_entry.get_text()),
            "distance": float(self.distance_entry.get_text()),
            "tasks": [t.options['enabled'] for  t , _ in self.TaskList]}
        config.save_config(SCREEN_CONFIG_FILE, data)
    
    def _load_config(self):
        data = config.load_config(SCREEN_CONFIG_FILE)
        if data is not None:
            self.folder_btn.select_filename(data.get('directory', os.environ['HOME']))
            self.time_entry.set_text('%0.2f' % data.get('time', self.beamline.config['default_exposure']))
            self.delta_entry.set_text('%0.2f' % data.get('delta', 1.0))
            self.distance_entry.set_text('%0.2f' % data.get('distance', 300.0))
            for idx, v in enumerate(data.get('tasks',[])):
                self.TaskList[idx][1].set_active(v)
        else:
            self.folder_btn.select_filename(os.environ['HOME'])
            self.time_entry.set_text('%0.2f' % self.beamline.config['default_exposure'])
            self.delta_entry.set_text('%0.2f' % 1.0)
            self.distance_entry.set_text('%0.2f' % 300.0)                  
        
    def _on_task_toggle(self, obj, tasklet):
        tasklet.configure(enabled=obj.get_active())
    
    def _on_sequence_apply(self, obj):
        model = self.listview.get_model()
        model.clear()
        items = self.sample_list.get_selected()
        delta = float(self.delta_entry.get_text())
        for item in items:
            collect_task = None
            collect_frames = []
            for t, _ in self.TaskList:
                if t.options['enabled']:
                    tsk = Tasklet(t.task_type, **t.options)
                    tsk.options.update({
                        'directory' : self.folder_btn.get_filename(),
                        'sample':  item})
                    if tsk.task_type == Screener.TASK_COLLECT:
                        for n in range(int(t.options['frames'])):
                            ang = t.options['angle'] + n*delta
                            num = int(round(ang/delta)) + 1
                            collect_frames.append(num)
                            
                        if collect_task is None:
                            collect_task = tsk
                            q_item = {'status': Screener.TASK_STATE_PENDING, 'task': tsk}
                            self._add_item(q_item)
                    else:
                        if tsk.task_type == Screener.TASK_ANALYSE:
                            # make sure analyse knows about corresponding collect
                            tsk.options.update(collect_task=collect_task)   
                        q_item = {'status': Screener.TASK_STATE_PENDING, 'task': tsk} 
                        self._add_item(q_item)
            
            # setup collect parameters for this item
            if collect_task is not None:
                collect_task.options.update({
                    'delta_angle': float(self.delta_entry.get_text()),
                    'exposure_time': float(self.time_entry.get_text()),
                    'distance': float(self.distance_entry.get_text()),
                    'energy': [float(self.energy_entry.get_text())],
                    'energy_label': ['E0'],
                    'first_frame': 1,
                    'start_angle': 0.0,
                    'wedge': 360.0,
                    'total_angle': (max(collect_frames)) * delta,
                    'skip': determine_skip(collect_frames),
                    'frame_set': summarize_frame_set(collect_frames),
                    })
                    
            # Add dismount task for last item
            if item == items[-1]:
                tsk = Tasklet(Screener.TASK_DISMOUNT)
                tsk.options.update(sample=item)
                self._add_item({'status': Screener.TASK_STATE_PENDING, 'task': tsk})
                
        # Save the configuration everytime we hit apply
        self._save_config()
  

    
    def _on_sequence_reset(self, obj):
        for t,b in self.TaskList:
            b.set_active(t.options['default'])

    def _on_queue_clear(self, obj):
        model = self.listview.get_model()
        model.clear()
        self.start_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(False)
    
    def _on_activate(self, obj):
        if not self._screening:
            self.start_time = time.time()
            task_list = self.get_task_list()       
            #FIXME: must configure user here before continuing
            self.screen_runner.configure(task_list)
            self.screen_runner.start()
        else:
            if self._screening_paused:
                self.screen_runner.resume()
            else:
                self.screen_runner.pause()
        self.stop_btn.set_sensitive(True)
                
    def _on_stop_btn_clicked(self,widget):
        self.screen_runner.stop()
        self.stop_btn.set_sensitive(False)
                          
    def _on_progress(self, obj, fraction, position, status=Screener.TASK_STATE_RUNNING):
        elapsed_time = time.time() - self.start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        if position > 0:
            text = "%0.0f %%, ETA %s" % (percent, time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        else:
            text = "Total: %s sec" % (time.strftime('%H:%M:%S',time.gmtime(elapsed_time)))
        self.scan_pbar.set_fraction(fraction)
        self.scan_pbar.set_text(text)

        # Update Queue state
        path = (position,)
        model = self.listview.get_model()
        iter = model.get_iter(path)
        model.set(iter, QUEUE_COLUMN_STATUS, status)
        self.listview.scroll_to_cell(path, use_align=True,row_align=0.4)
        
        # determine current and next tasks
        if iter is None:
            self.lbl_current.set_text('')
        else:
            cur_tsk = model.get_value(iter, QUEUE_COLUMN_TASK)
            cur_sample = cur_tsk['sample']['path'] # location in sample list
            txt = str(cur_tsk)
            self.lbl_current.set_text(txt)
            next_iter = model.iter_next(iter)
            if next_iter is not None:
                next_tsk = model.get_value(next_iter, QUEUE_COLUMN_TASK)
                next_sample = next_tsk['sample']['path'] # location in sample list
                txt = str(next_tsk)
                self.lbl_next.set_text(txt)
            else:
                self.lbl_next.set_text('')
                next_sample = None
            if cur_sample != next_sample and status == Screener.TASK_STATE_DONE:
                self.sample_list.set_row_processed(cur_sample, True)
                self.sample_list.set_row_selected(cur_sample, False)
       
        #self.lbl_current.set_alignment(0.5, 0.5)
        #self.lbl_next.set_alignment(0.5, 0.5)

        
    def _on_stop(self, obj):
        self._screening = False
        self._screening_paused = False
        self.start_btn.set_label('mxdc-start')
        self.stop_btn.set_sensitive(False)
        self.scan_pbar.set_text("Stopped")
        self.action_frame.set_sensitive(True)

    def _on_pause(self, obj, state, pause_dict):
        # Build the dialog message
        msg = ''
        if 'type' in pause_dict:
            msg = PAUSE_MSGS[pause_dict['type']]
        if ('task' and 'sample' and 'port') in pause_dict:
            msg += 'task <b>"%s"</b> ' % pause_dict['task']
            msg += 'on sample <b>"%s(%s)</b>"' % (pause_dict['sample'], pause_dict['port'])

        if state:
            self._screening_paused = True
            self.start_btn.set_label('mxdc-resume')
        else:
            self._screening_paused = False
            self.start_btn.set_label('mxdc-pause')
        self.stop_btn.set_sensitive(True)
        self.scan_pbar.set_text("Paused")
        if msg:
            title = 'Attention Required'
            self.resp = MyDialog(gtk.MESSAGE_WARNING, 
                                         title, msg,
                                         buttons=( ('Intervene', gtk.RESPONSE_ACCEPT),) )
            self._intervening = False
            if pause_dict['type'] is Screener.PAUSE_BEAM: 
                self.beam_connect = self.beamline.storage_ring.connect('beam', self._on_beam_change)
                try:
                    self.collect_obj = pause_dict['collector']
                    self.data_collector.set_position(pause_dict['position'])
                except:
                    self.collect_obj = False
            response = self.resp()
            if response == gtk.RESPONSE_ACCEPT or (pause_dict['type'] == Screener.PAUSE_BEAM and self._beam_up):
                self._intervening = True
                self._beam_up = False
                if self.collect_obj:
                    self.resume_labels = self.start_btn.connect('clicked', self._on_resume)
                if self.beam_connect:
                    self.beamline.storage_ring.disconnect(self.beam_connect)
                return

    def _on_resume(self, obj=None):
        self.scan_pbar.set_text("Resuming")
        self.start_btn.set_label('mxdc-pause')
        if self.resume_labels: self.start_btn.disconnect(self.resume_labels)

    def _on_beam_change(self, obj, beam_available):
        
        def resume_screen(script, obj):
            if self.collect_obj: 
                self._on_resume()
            self._screening_paused = False
            self.screen_runner.resume()
            self.resp.dialog.destroy()
            s.disconnect(self.resume_connect)
            
        if beam_available and not self._intervening and self._screening_paused:
            self._beam_up = True
            s = self.scripts['RestoreBeam']
            self.resume_connect = s.connect('done', resume_screen )
            s.start()
        return True
        
    def _on_start(self, obj):
        self._screening = True
        self._screening_paused = False
        self.start_btn.set_label('mxdc-pause')
        self.stop_btn.set_sensitive(True)
        self.action_frame.set_sensitive(False)
        self.clear_btn.set_sensitive(False)
        self.image_viewer.set_collect_mode(True)
        self.start_time = time.time()
    
    def _on_complete(self, obj):
        self._screening = False
        self._screening_paused = False
        self.start_btn.set_label('mxdc-start')
        self.stop_btn.set_sensitive(False)
        self.action_frame.set_sensitive(True)
        self.clear_btn.set_sensitive(True)

    def _on_diffraction_image(self, obj, pos, filename):
        self.image_viewer.add_frame(filename)       
        # make tab label bold if image is loaded while hidden
        if self.screen_ntbk.get_current_page() != self.screen_ntbk.page_num(self.image_viewer):
            tab = self.screen_ntbk.get_tab_label(self.image_viewer)
            tab.label.set_markup("<b>%s</b>"% tab.label.get_text())
            tab.icon.set_from_pixbuf(self._info_img)
    
    def _on_page_switch(self, obj, pg, pgn):
        if pgn == self.screen_ntbk.page_num(self.image_viewer):
            # restore label to normal
            wdg = obj.get_nth_page(pgn)
            tab = obj.get_tab_label(wdg)
            tab.label.set_text(tab.label.get_text())
            tab.icon.set_from_pixbuf(None)
        
    def _on_show_raster(self, obj):
        # switch video tab to sample viewer
        self.video_book.set_current_page(self.video_book.page_num(self.sample_viewer))
        
