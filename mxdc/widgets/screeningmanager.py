import os
import time
import gtk
import gtk.glade
import gobject
from twisted.python.components import globalRegistry
from mxdc.widgets.samplelist import SampleList
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets import dialogs
from mxdc.widgets.ptzviewer import AxisViewer
from bcm.beamline.mx import IBeamline
from bcm.engine.interfaces import IDataCollector
from bcm.engine.diffraction import Screener, DataCollector

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

TASKLET_NAME_MAP = {
    Screener.TASK_MOUNT : 'Mount Crystal',
    Screener.TASK_ALIGN : 'Align Crystal',
    Screener.TASK_PAUSE : 'Pause',
    Screener.TASK_COLLECT : 'Collect',
    Screener.TASK_ANALYSE : 'Analyse',
}

(
    QUEUE_COLUMN_DONE,
    QUEUE_COLUMN_ID,
    QUEUE_COLUMN_NAME,
    QUEUE_COLUMN_TASK,
) = range(4)

class Tasklet(object):
    def __init__(self, task_type, **kwargs):
        self.options = {}
        self.name = TASKLET_NAME_MAP[task_type]
        self.task_type = task_type
        self.configure(**kwargs)
    
    def configure(self, **kwargs):
            self.options.update(kwargs)

    def __repr__(self):
        return '<Tasklet: %s, %s>' % (self.name, self.options)
    
    def __getitem__(self, key):
        return self.options[key]

class ScreenManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
                                  'screening_widget')

        self._create_widgets()
        self.screen_runner = Screener()
        self._screening = False
        self._screening_paused = False
        self.screen_runner.connect('progress', self._on_progress)
        self.screen_runner.connect('stopped', self._on_stop)
        self.screen_runner.connect('paused', self._on_pause)
        self.screen_runner.connect('started', self._on_start)
        self.screen_runner.connect('done', self._on_complete)

        
    def __getattr__(self, key):
        try:
            return super(ScreenManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):        
        self.sample_list = SampleList()

        self.screen_manager = self._xml.get_widget('screening_widget')
        #self.export_btn.connect('clicked', self._on_export)
        #self.import_btn.connect('clicked', self._on_import)

        self.clear_btn.connect('clicked', self._on_queue_clear)
        self.apply_btn.connect('clicked', self._on_sequence_apply)
        self.reset_btn.connect('clicked', self._on_sequence_reset)
        self.select_all_btn.connect('clicked', lambda x: self.sample_list.select_all(True) )
        self.deselect_all_btn.connect('clicked', lambda x: self.sample_list.select_all(False) )
        #self.edit_tbtn.connect('toggled', self.sample_list.on_edit_toggled)
        self.start_btn.connect('clicked', self._on_activate)
        self.stop_btn.connect('clicked', self._on_stop_btn_clicked)
        self.start_btn.set_label('mxdc-start')
        self.stop_btn.set_label('mxdc-stop')
        
        self.beamline = globalRegistry.lookup([], IBeamline)

        self.sample_box.pack_start(self.sample_list, expand=True, fill=True)
        #self.sample_list.import_csv(os.path.join(DATA_DIR, 'test.csv')) 

        # video        
        self.sample_viewer = SampleViewer()
        self.image_viewer = ImageViewer()
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.video_book.append_page(self.sample_viewer, tab_label=gtk.Label('Sample Camera'))
        self.video_book.append_page(self.hutch_viewer, tab_label=gtk.Label('Hutch Camera'))
        self.video_book.append_page(self.image_viewer, tab_label=gtk.Label('Diffraction Viewer'))
        self.video_book.connect('realize', lambda x: self.video_book.set_current_page(0))       
        
        #create a data collector and attach it to diffraction viewer
        self.data_collector = DataCollector()
        self.data_collector.connect('new-image', self.on_diffraction_image)
        globalRegistry.register([], IDataCollector, 'mxdc.screening', self.data_collector)
        
        # Task Configuration
        self.TaskList = []
        self.default_tasks = [ 
                  (Screener.TASK_MOUNT, {'default': True}),
                  (Screener.TASK_ALIGN, {'default': True}),
                  (Screener.TASK_PAUSE, {'default': False}), # use this line for collect labels
                  (Screener.TASK_COLLECT, {'angle': 0.0, 'default': True}),
                  (Screener.TASK_COLLECT, {'angle': 45.0, 'default': False}),
                  (Screener.TASK_COLLECT, {'angle': 90.0, 'default': True}),
                  (Screener.TASK_ANALYSE, {'default': False}),
                  (Screener.TASK_PAUSE, {'default': False}), ]
        self._settings_sg = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        
        # connect signals for collect parameters
        self.delta_entry.connect('activate', self._on_entry_changed, None)
        self.delta_entry.connect('focus-out-event', self._on_entry_changed)
        self.time_entry.connect('activate', self._on_entry_changed, None)
        self.time_entry.connect('focus-out-event', self._on_entry_changed)
        
        for pos, tasklet in enumerate(self.default_tasks):
            key, options = tasklet
            options.update({'enabled': options['default']})
            t = Tasklet(key, **options)
            tbtn = gtk.CheckButton(t.name)
            tbtn.set_active(options['default'])
            tbtn.connect('toggled', self._on_task_toggle, t)
            tbtn.set_sensitive(not(options['default']))

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
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT,
        )
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self._add_columns()
        self.task_queue_window.add(self.listview)    

        self.add(self.screen_manager) 
        self.show_all()
    
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
        _xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
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
        _xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
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
    
    def _on_entry_changed(self, obj, event):
        try:
            val = float( obj.get_text() )
            val = max(0.2, val)
            obj.set_text( '%0.1f' % val )
        except:
            val = obj.default_value
            obj.set_text( '%0.1f' % val )
            
        
       
    def _add_item(self, item):
        iter = self.listmodel.append()
        self.listmodel.set(iter, 
            QUEUE_COLUMN_DONE, item['done'], 
            QUEUE_COLUMN_ID, item['task'].options['sample']['id'],
            QUEUE_COLUMN_NAME, item['task'].name,
            QUEUE_COLUMN_TASK, item['task'],
        )
        self.start_btn.set_sensitive(True)
        
    def _done_color(self, column, renderer, model, iter):
        value = model.get_value(iter, QUEUE_COLUMN_DONE)
        if value:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return

    def _add_columns(self):
        model = self.listview.get_model()
                                          
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
    
    def _on_task_toggle(self, obj, tasklet):
        tasklet.configure(enabled=obj.get_active())
    
    def _on_sequence_apply(self, obj):
        model = self.listview.get_model()
        model.clear()
        items = self.sample_list.get_selected()
        for item in items:
            for t,b in self.TaskList:
                if t.options['enabled']:
                    tsk = Tasklet(t.task_type, **t.options)
                    tsk.options.update({
                        'directory' : self.folder_btn.get_current_folder(),
                        'sample':  item})
                    if tsk.task_type == Screener.TASK_COLLECT:
                        st_fr = 1 + tsk.options['angle']//float(self.delta_entry.get_text())
                        tsk.options.update({
                            'delta': float(self.delta_entry.get_text()),
                            'time': float(self.time_entry.get_text()),
                            'start_frame':st_fr})
                    q_item = {'done': False, 'task': tsk} 
                    self._add_item(q_item)
  

    def _on_export(self, obj):
        _CSV = 'Comma Separated Values'
        _XLS = 'Excel 97-2003'
        filters = [
            (_XLS, ['*.xls']),
            (_CSV, ['*.csv']),
        ]
        export_selector = dialogs.FileSelector('Export Spreadsheet',
                                       gtk.FILE_CHOOSER_ACTION_SAVE,
                                       filters=filters)
        filename = export_selector.run()
        filter = export_selector.get_filter()
        if filename is None:
            return
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.csv':
            self.sample_list.export_csv(filename)
        elif ext == '.xls':
            self.sample_list.export_xls(filename)
        else:
            format = filter.get_name()
            if format == _CSV:
                self.sample_list.export_csv(filename)
            elif format == _XLS:
                self.sample_list.export_xls(filename)
            
    def _on_import(self, obj):
        _ALL = 'All Files'
        _CSV = 'Comma Separated Values'
        _XLS = 'Excel 97-2003'
        filters = [
            (_XLS, ['*.xls']),
            (_CSV, ['*.csv']),
            (_ALL, ['*']),
        ]
        export_selector = dialogs.FileSelector('Import Spreadsheet',
                                       gtk.FILE_CHOOSER_ACTION_OPEN,
                                       filters=filters)
        filename = export_selector.run()
        filter = export_selector.get_filter()
        if filename is None:
            return
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.csv':
            self.sample_list.import_csv(filename)
        elif ext == '.xls':
            self.sample_list.import_xls(filename)
        else:
            format = filter.get_name()
            if format == _CSV:
                self.sample_list.import_csv(filename)
            elif format == _XLS:
                self.sample_list.import_xls(filename)
            elif format == _ALL:
                try:
                    self.sample_list.import_csv(filename)
                except:
                    try:
                        self.sample_list.import_xls(filename)
                    except:
                        header = 'Unknown file format'
                        subhead = 'The file "%s" could not be opened' % filename
                        dialogs.error(header, subhead)

    
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
                          
    def _on_progress(self, obj, fraction, position):
        if position == 1:
            self.start_time = time.time()
        elapsed_time = time.time() - self.start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        if position > 0:
            frame_time = elapsed_time / position
            text = "%0.0f %%, ETA %s" % (percent, time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        else:
            text = "Total: %s sec" % (time.strftime('%H:%M:%S',time.gmtime(elapsed_time)))
        self.scan_pbar.set_fraction(fraction)
        self.scan_pbar.set_text(text)

        # Update Queue state
        path = (position,)
        model = self.listview.get_model()
        iter = model.get_iter(path)
        model.set(iter, QUEUE_COLUMN_DONE, True)
        self.listview.scroll_to_cell(path, use_align=True,row_align=0.9)

        
    def _on_stop(self, obj):
        self._screening = False
        self._screening_paused = False
        self.start_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.scan_pbar.set_text("Stopped")
        self.action_frame.set_sensitive(True)

    def _on_pause(self, obj, state, msg):
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
            resp = dialogs.messagedialog(gtk.MESSAGE_WARNING, 
                                         title, msg,
                                         buttons=( ('Intervene', gtk.RESPONSE_ACCEPT), 
                                                   ('mxdc-resume', gtk.RESPONSE_CANCEL)) )
            if resp == gtk.RESPONSE_ACCEPT:
                return
            elif resp == gtk.RESPONSE_CANCEL:
                self.screen_runner.resume()

    def _on_start(self, obj):
        self._screening = True
        self._screening_paused = False
        self.start_btn.set_label('mxdc-pause')
        self.stop_btn.set_sensitive(True)
        self.action_frame.set_sensitive(False)
        self.clear_btn.set_sensitive(False)
        self.image_viewer.set_collect_mode(True)
    
    def _on_complete(self, obj):
        self._screening = False
        self._screening_paused = False
        self.start_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.action_frame.set_sensitive(True)
        self.clear_btn.set_sensitive(True)

    def on_diffraction_image(self, obj, pos, filename):
        self.image_viewer.add_frame(filename)
    