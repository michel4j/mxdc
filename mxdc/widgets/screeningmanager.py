import sys
import os
import gtk
import gtk.glade
import gobject
from twisted.python.components import globalRegistry
from mxdc.widgets.samplelist import SampleList, TEST_DATA
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.ptzviewer import AxisViewer
from bcm.beamline.mx import IBeamline
from bcm.engine.scripting import get_scripts

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
( TASK_MOUNT,
  TASK_ALIGN,
  TASK_PAUSE,
  TASK_COLLECT,
  TASK_ANALYSE ) = range(5)

TASKLET_NAME_MAP = {
    TASK_MOUNT : 'Mount Crystal',
    TASK_ALIGN : 'Align Crystal',
    TASK_PAUSE : 'Pause',
    TASK_COLLECT : 'Collect',
    TASK_ANALYSE : 'Analyse',
}

(
    QUEUE_COLUMN_DONE,
    QUEUE_COLUMN_ID,
    QUEUE_COLUMN_NAME,
    QUEUE_COLUMN_TASK
) = range(4)

class Tasklet(object):
    def __init__(self, task_type, default=False):
        self.name = TASKLET_NAME_MAP[task_type]
        self.options = {'enabled': default, 'default': default}      
        self.task_type = task_type
        
    
    def configure(self, **kwargs):
        for k,v in kwargs.items():
            self.options[k] = v

    def __repr__(self):
        return '<Tasklet: %s>' % self.name

class ScreenManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._create_widgets()
        
    def _create_widgets(self):        
        self.sample_list = SampleList()

        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
                                  'screening_widget')
        self.screen_manager = self._xml.get_widget('screening_widget')
        self.sample_box = self._xml.get_widget('sample_box')
        self.video_book = self._xml.get_widget('video_book')
        self.task_config_box = self._xml.get_widget('task_config_box')
        self.apply_btn = self._xml.get_widget('apply_btn')
        self.reset_btn = self._xml.get_widget('reset_btn')
        self.clear_btn = self._xml.get_widget('clear_btn')
        self.select_all_btn = self._xml.get_widget('select_all_btn')
        self.deselect_all_btn = self._xml.get_widget('deselect_all_btn')
        self.task_queue_window = self._xml.get_widget('task_queue_window')
        self.edit_tbtn = self._xml.get_widget('edit_tbtn')
        
        self.clear_btn.connect('clicked', self._on_queue_clear)
        self.apply_btn.connect('clicked', self._on_sequence_apply)
        self.reset_btn.connect('clicked', self._on_sequence_reset)
        self.select_all_btn.connect('clicked', lambda x: self.sample_list.select_all(True) )
        self.deselect_all_btn.connect('clicked', lambda x: self.sample_list.select_all(False) )
        self.edit_tbtn.connect('toggled', self.sample_list.on_edit_toggled)
        
        self.beamline = globalRegistry.lookup([], IBeamline)

        self.sample_box.pack_start(self.sample_list, expand=True, fill=True)
        self.sample_list.import_csv(os.path.join(DATA_DIR, 'test.csv')) 
        #self.sample_list.load_data(TEST_DATA)

        # video        
        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.video_book.append_page(self.sample_viewer, tab_label=gtk.Label('Sample Camera'))
        self.video_book.append_page(self.hutch_viewer, tab_label=gtk.Label('Hutch Camera'))
        self.video_book.connect('map', lambda x: self.video_book.set_current_page(0))       
        
        # Task Configuration
        self.TaskList = []
        self.default_tasks = [ (TASK_MOUNT, True, True),
                  (TASK_ALIGN, True, True),
                  (TASK_PAUSE, False, False),
                  (TASK_COLLECT, True, True),
                  (TASK_COLLECT, True, False),
                  (TASK_COLLECT, False, False),
                  (TASK_ANALYSE, False, False),
                  (TASK_PAUSE, False, False), ]
        for key, sel, sen in self.default_tasks:
            t = Tasklet(key, default=sel)
            tbtn = gtk.CheckButton(t.name)
            tbtn.set_active(sel)
            tbtn.connect('toggled', self._on_task_toggle, t)
            tbtn.set_sensitive(not(sen))
            if key == TASK_COLLECT:
                ctable = self._get_collect_setup(t)
                ctable.attach(tbtn, 0,2,0,1)
                self.task_config_box.pack_start(ctable, expand=True, fill=True)
            else:
                self.task_config_box.pack_start(tbtn, expand=True, fill=True)
            self.TaskList.append( (t, tbtn) )
        
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
    
    def _get_collect_setup(self, task):
        _xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
                          'collect_settings')
        tbl = _xml2.get_widget('collect_settings')
        for key in ['angle','delta','time','frames']:
            en = _xml2.get_widget('%s_entry' % key)
            if key == 'frames':
                en.default_value = int(en.get_text())
            else:
                en.default_value = float(en.get_text())
            task.options[key] = en.default_value
            en.connect('activate', self._on_settings_changed, None, task, key)
            en.connect('focus-out-event', self._on_settings_changed, task, key)
            en.set_alignment(1)
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
        
    def _add_item(self, item):
        iter = self.listmodel.append()
        self.listmodel.set(iter, 
            QUEUE_COLUMN_DONE, item['done'], 
            QUEUE_COLUMN_ID, item['id'],
            QUEUE_COLUMN_NAME, item['name'],
            QUEUE_COLUMN_TASK, item['task'],
        )
        
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
                    item['done'] = False
                    item['name'] = t.name
                    item['task'] = t
                    self._add_item(item)
    
    def _on_sequence_reset(self, obj):
        for t,b in self.TaskList:
            b.set_active(t.options['default'])

    def _on_queue_clear(self, obj):
        model = self.listview.get_model()
        model.clear()
    
    def _on_collect_setup(self, obj):
        pass