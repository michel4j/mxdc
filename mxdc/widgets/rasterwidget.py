import os
import gobject
import gtk
import time
import numpy

from datetime import datetime
from bcm.utils import misc
from mxdc.widgets import dialogs
from mxdc.utils.xlsimport import XLSLoader
from mxdc.utils import gui, config

from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline

_CONFIG_FILE = 'raster_config.json'

(
    RASTER_STATE_IDLE,
    RASTER_STATE_RUNNING,
    RASTER_STATE_PAUSED
) = range(3)


class ResultStore(gtk.ListStore):
    (   
        NAME,
        ANGLE,
        ACTIVE,
        DATA,
    ) = range(4)
    
    def __init__(self):
        gtk.ListStore.__init__(self,                
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_PYOBJECT
            )

    def add_item(self, item):
        iter = self.get_iter_first()
        while iter:
            self.set_value(iter, self.ACTIVE, False)
            iter = self.iter_next(iter)
        iter = self.append()
        self.set(iter, 
            self.NAME, item['name'],
            self.ANGLE, "%0.2f" % item['angle'],
            self.ACTIVE, True,
            self.DATA, item)
                    
class DetailStore(gtk.ListStore):
    (
        NAME,
        XPOS,
        YPOS,
        SCORE,
        DATA,
    ) = range(5)
    
    def __init__(self):
        gtk.ListStore.__init__(self,
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT,
            )
      
    def add_item(self, item):
        iter = self.append()
        self.set(iter,
            self.NAME, item['name'],
            self.XPOS, "%0.3f" % item['xpos'],
            self.YPOS, "%0.3f" % item['ypos'],
            self.SCORE, "%0.2f" % item['score'])
            
    def add_items(self, results):
        self.clear()
        for cell, score in results.get('scores', {}).items():
            loc = results['cells'][cell]
            self.add_item({
                'name': '(%d,%d)' % cell,
                'xpos': loc[2],
                'ypos': loc[3],
                'score': score})
         
class RasterWidget(gtk.Frame):    
    __gsignals__ = {
        'show-raster': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'show-image':  (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT)),
    }
    
    def do_show_raster(self):
        pass

    def do_show_image(self, cell, filename):
        pass
    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gui.GUIFile(
                        os.path.join(os.path.dirname(__file__), 'data', 'raster_widget'),
                        'raster_vbox')

        self.add(self.raster_vbox)

        #results pane
        self.results_view = self.__create_result_view()
        self.results_view.connect('row-activated',self.on_result_activated)
        self.results_sw.add(self.results_view)

        #details pane
        self.details_view = self.__create_detail_view()
        self.details_view.connect('row-activated',self.on_detail_activated)
        self.details_sw.add(self.details_view)
                
        #btn commands
        self.apply_btn.connect('clicked', self.on_apply)
        self.reset_btn.connect('clicked', self.on_reset)
        self.clear_btn.connect('clicked', self.on_clear)
        self.action_btn.connect('clicked', self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop)

        self.sample_viewer = None
        self.collector = None
        self._state = RASTER_STATE_IDLE
        self._last_progress_fraction = 0.0
        self.action_btn.set_label('mxdc-start')
        self.stop_btn.set_sensitive(False)

        self.beamline = globalRegistry.lookup([], IBeamline)      

        self.entries = {
            'prefix': self.prefix_entry,
            'directory': self.folder_btn,
            'aperture': self.aperture_entry,
            'loop_size': self.loop_entry,
            'time': self.time_entry,
            'distance': self.distance_entry,
        }

        self._load_config()
        self.entries['prefix'].connect('focus-out-event', lambda x,y: self._validate_slug(x, 'test'))
        self.entries['loop_size'].connect('focus-out-event', lambda x,y: self._validate_float(x, 200.0, 20.0, 1000.0))
        self.entries['distance'].connect('focus-out-event', lambda x,y: self._validate_float(x, 250.0, 100.0, 1000.0))
        self.entries['time'].connect('focus-out-event', lambda x,y: self._validate_float(x, 1.0, 0.1, 500))
        self.beamline.aperture.connect('changed', self._set_aperture)
        
    def __getattr__(self, key):
        try:
            return super(RasterWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
    
    def _set_aperture(self, ap, val):
        self.entries['aperture'].set_text('%0.1f' % val)
        
    def __create_result_view(self):
        self.results = ResultStore()
        model = self.results

        treeview = gtk.TreeView(self.results)
        treeview.set_rules_hint(True)

        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_result_activated)
        renderer.set_radio(True)
        column = gtk.TreeViewColumn('', renderer, active=model.ACTIVE)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)
        treeview.append_column(column)

        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Name', renderer, text=model.NAME)
        treeview.append_column(column)
               
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Angle', renderer, text=model.ANGLE)
        column.set_cell_data_func(renderer, self.__set_format)
        treeview.append_column(column)
        
        treeview.connect('row-activated',self.on_result_activated)
        return treeview
        
    def __create_detail_view(self):
        self.details = DetailStore()
        model = self.details
        treeview = gtk.TreeView(self.details)
        treeview.set_rules_hint(True)

        # columns for Name, X and Y
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Grid Cell", renderer, text=model.NAME)
        treeview.append_column(column)

        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("X", renderer, text=model.XPOS)
        treeview.append_column(column)
        
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Y", renderer, text=model.YPOS)
        treeview.append_column(column)

        # column for score
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Score", renderer, text=model.SCORE)
        treeview.append_column(column)

        return treeview
    
    def _validate_float(self, entry, default, min_val, max_val):
        try:
            value = float(entry.get_text().split()[0])
        except:
            value = default
        value = max(min(value, max_val), min_val)
        entry.set_text('%0.1f' % value)
    
    def _validate_int(self, entry, default, min_val, max_val):
        try:
            value = int(entry.get_text().split()[0])
        except:
            value = default
        value = max(min(value, max_val), min_val)
        entry.set_text('%d' % value)

    def _validate_slug(self, entry, default):
        value = entry.get_text()
        value = misc.slugify(value.strip(), empty=default)
        entry.set_text(value)
    
    def link_viewer(self, sampleviewer):
        """Attach a sample viewer to this widget"""
        self.sample_viewer = sampleviewer

    def link_collector(self, collector):
        """Attach a raster collector to this widget"""
        if self.collector is None:
            self.collector = collector
            self.collector.connect('progress', self.on_raster_progress)
            self.collector.connect('stopped', self.on_raster_stopped)
            self.collector.connect('paused', self.on_raster_paused)
            self.collector.connect('started', self.on_raster_started)
            self.collector.connect('done', self.on_raster_completed)
            self.collector.connect('new-fluor', self.on_new_fluor)
            self.collector.connect('new-result', self.on_new_result)
        
    def set_parameters(self, params=None):
        if params is None:
            # load defaults
            params = {
                'mode': 'Diffraction',
                'prefix': 'test',
                'directory': os.environ['HOME'],
                'distance': self.beamline.distance.get_position(),
                'loop_size': 200,
                'aperture': self.beamline.aperture.get(),
                'time': self.beamline.config.get('default_exposure'),
                'delta': 1.0
            }
        self.entries['prefix'].set_text(params['prefix'])
        if params.get('directory') is not None:
            self.entries['directory'].select_filename("%s" % params['directory'])
        for key in ['time','loop_size', 'distance', 'aperture']:
            self.entries[key].set_text("%0.1f" % params[key])
            
        if params['mode'] == 'Diffraction':
            self.diff_btn.set_active(True)
        else:
            self.fluor_btn.set_active(True)


        
    def get_parameters(self):
        params = {}
        params['prefix']  = self.entries['prefix'].get_text().strip()
        params['directory']   = self.entries['directory'].get_filename()
        
        for key in ['time','loop_size','distance', 'aperture']:
            params[key] = float(self.entries[key].get_text())
        if params['directory'] is None:
            params['directory'] = os.environ['HOME']
        if self.diff_btn.get_active():
            params['mode'] = 'Diffraction'
        else:
            params['mode'] = 'Fluorescence'
        params['delta'] = 1.0
        return params

    def _load_config(self):
        data = config.load_config(_CONFIG_FILE)
        self.set_parameters(data)

    def _save_config(self, parameters):
        config.save_config(_CONFIG_FILE, parameters)

    def on_detail_activated(self, treeview, path, column=None):
        pass
       
    def on_result_activated(self, cell, path, column=None):
        iter = self.results.get_iter_first()
        while iter:
            self.results.set_value(iter, ResultStore.ACTIVE, False)
            iter = self.results.iter_next(iter)
        iter = self.results.get_iter(path)
        self.results.set_value(iter, ResultStore.ACTIVE, True)
        data = self.results.get_value(iter, ResultStore.DATA)
        self.details.add_items(data)
        self.beamline.omega.move_to(data['angle'], wait=False)
        self.sample_viewer.apply_grid_results(data)
        return True
    
    def on_apply(self, btn):
        if self.sample_viewer:
            gobject.idle_add(self.emit, 'show-raster')
            params = self.get_parameters()
            config.save_config(_CONFIG_FILE,params)
            self.sample_viewer.apply_grid_settings(params)
            self.action_btn.set_sensitive(True)
              
    def on_reset(self, btn):
        self.set_parameters()
    
    def on_clear(self, btn):
        if self.sample_viewer:
            self.sample_viewer.clear_grid()
            self.action_btn.set_sensitive(False)
    
    def on_activate(self, btn):
        if self.sample_viewer and self.collector:
            self.action_btn.set_sensitive(False)
            if self._state == RASTER_STATE_IDLE:
                params = self.get_parameters()
                config.save_config(_CONFIG_FILE,params)
                info = self.sample_viewer.get_grid_settings()
                self.sample_viewer.lock_grid()
                info.update(params)
 
                self._result_info = info
                self._result_info['name'] = "%s-%s" % (self._result_info['prefix'], datetime.now().strftime('%H:%M:%S'))

                self.collector.configure(info)
                self.pbar.set_text("Starting ... ")
                self.collector.start()
                self.result_box.set_sensitive(False)
            elif self._state == RASTER_STATE_RUNNING:
                self.pbar.set_text("Pausing ... ")
                self.collector.pause()
            elif self._state == RASTER_STATE_PAUSED:
                self.on_raster_progress()
                self.collector.resume()
    
    def on_stop(self, btn):
        if self.collector:
            self.pbar.set_text("Stopping ... ")
            self.collector.stop()
       
    def on_raster_progress(self, obj=None, fraction=None):
        if fraction is None:
            fraction = self._last_progress_fraction
        else:
            self._last_progress_fraction = fraction
        elapsed_time = time.time() - self.start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        if fraction < 1.0:
            text = "%0.0f %%, ETA %s" % (percent, time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        else:
            text = "Done in: %s sec" % (time.strftime('%H:%M:%S',time.gmtime(elapsed_time)))
        self.pbar.set_fraction(fraction)
        self.pbar.set_text(text)

        
    def on_raster_stopped(self, obj):
        self.stop_btn.set_sensitive(False)
        self._state = RASTER_STATE_IDLE
        self.action_btn.set_label('mxdc-start')
        self.pbar.set_text("Stopped!")
        self.control_box.set_sensitive(True)
        self.score_options.set_sensitive(True)
        self.results.add_item(self._result_info)
        self.details.add_items(self._result_info)           
        self.result_box.set_sensitive(True)          

    def on_raster_paused(self, obj, state):
        if state:
            self.pbar.set_text("Paused")
            self.action_btn.set_label('mxdc-resume')
            self._state = RASTER_STATE_PAUSED
        else:
            self.action_btn.set_label('mxdc-pause')
            self._state = RASTER_STATE_RUNNING        
        self.action_btn.set_sensitive(True)
        
    def on_raster_started(self, obj):
        self.control_box.set_sensitive(False)
        self.score_options.set_sensitive(False)
        self.start_time = time.time()
        self.action_btn.set_label('mxdc-pause')
        self.stop_btn.set_sensitive(True)
        self.pbar.set_fraction(0.0)
        self.action_btn.set_sensitive(True)
        self._state = RASTER_STATE_RUNNING
        
        # Demo grid scores based on size
        self._scores_for_demo = _demo_scores(self._result_info['size'])
    
    def on_raster_completed(self, obj):
        self.stop_btn.set_sensitive(False)
        self.action_btn.set_label('mxdc-start')
        self.control_box.set_sensitive(True)
        self.score_options.set_sensitive(True)
        self._state = RASTER_STATE_IDLE
        self.results.add_item(self._result_info)
        self.details.add_items(self._result_info)
        self.result_box.set_sensitive(True)          
        
    def on_new_result(self, obj, cell, results):
        score = _score_diff(results)
        # demo override
        score = self._scores_for_demo[cell[0], cell[1]]

        self.sample_viewer.add_grid_score(cell, score)
        self._result_info['scores'][cell] = score
        
        
    def on_new_fluor(self, obj, cell, counts):
        pass


def _demo_scores(N):
    import matplotlib.mlab as mlab
    x = numpy.arange(-3.0, 3.0, 6.0/N)
    y = numpy.arange(-2.0, 2.0, 4.0/N)
    X, Y = numpy.meshgrid(x, y)
    Z1 = mlab.bivariate_normal(X, Y, 1.0, 0.75, 0.0, 0.0)
    Z2 = mlab.bivariate_normal(X, Y, 1.5, 0.5, 1, 1)
    # difference of Gaussians
    Z = (Z1 - Z2)
    Z = Z - min(Z.ravel())
    return Z / max(Z.ravel()) 
           

def _score_diff(results):

    def score_penalty(x, best, worst):
        if best > worst:
            x = min(best, max(worst, x))
        else:
            x = max(best, min(worst, x))
        
        x = (x-worst)/float(best-worst)
        return numpy.sqrt(1 - x*x)
    
    if not results:
        return 0.0
    
    resolution = max(results['resolution'], results['alt_resolution'])
    bragg = results['bragg_spots']/float(results['total_spots'])
    inres = results['resolution_spots']/float(results['total_spots'])
    saturation = results['saturation'][1];
    
    score = [ 1.0,
        -0.30 * score_penalty(resolution, 1.0, 10.0),
        -0.20 * score_penalty(bragg, 1.0, 0.0),
        -0.10 * score_penalty(inres, 1.0, 0.0),
        -0.10 * score_penalty(saturation, 50.0, 0.0),
        -0.10 * score_penalty(results['ice_rings'], 0, 8),
        ]
        
    return sum(score)
