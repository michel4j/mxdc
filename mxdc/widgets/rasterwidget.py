from bcm.beamline.mx import IBeamline
from bcm.utils import misc
from bcm.utils.decorators import async
from datetime import datetime
from mxdc.utils import gui, config
from mxdc.widgets.misc import MotorEntry, ActiveEntry
from mxdc.widgets import dialogs
from twisted.python.components import globalRegistry
import gobject
import gtk
import numpy
import os
import time

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
        itr = self.get_iter_first()
        while itr:
            self.set_value(itr, self.ACTIVE, False)
            itr = self.iter_next(itr)
        itr = self.append()
        self.set(itr, 
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
            gobject.TYPE_FLOAT,
            gobject.TYPE_PYOBJECT,
            )
        self.set_sort_column_id(self.SCORE, gtk.SORT_DESCENDING)

      
    def add_item(self, item):
        itr = self.append()
        self.set(itr,
            self.NAME, "(%d,%d)" % item['cell'],
            self.XPOS, "%0.3f" % item['xpos'],
            self.YPOS, "%0.3f" % item['ypos'],
            self.SCORE, round(item['score'],1),
            self.DATA, item)
            
    def add_items(self, results):
        self.clear()
        for cell, score in results.get('scores', {}).items():
            loc = results['cells'][cell]
            self.add_item({
                'cell': cell,
                'xpos': loc[2],
                'ypos': loc[3],
                'score': score})
         
class RasterWidget(gtk.Frame):    
    __gsignals__ = {
        'show-raster': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'show-image':  (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
    }
    
    def do_show_raster(self):
        pass

    def do_show_image(self, filename):
        pass
    
    def __init__(self):
        gtk.Frame.__init__(self, '')
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
        self.details_view.connect('cursor-changed', self.on_detail_selected)
        self.details_sw.add(self.details_view)
                
        #btn commands
        self.apply_btn.connect('clicked', self.on_apply)
        self.reset_btn.connect('clicked', self.on_reset)
        self.clear_btn.connect('clicked', self.on_clear)
        self.action_btn.connect('clicked', self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop)

        self.sample_viewer = None
        self.collector = None
        self._status = RASTER_STATE_IDLE
        self._last_progress_fraction = 0.0
        self.action_btn.set_label('mxdc-start')
        self.stop_btn.set_sensitive(False)

        self.beamline = globalRegistry.lookup([], IBeamline)      

        self.entries = {
            'prefix': self.prefix_entry,
            'directory': dialogs.FolderSelector(self.folder_btn),
            'loop_size': self.loop_entry,
            'time': self.time_entry,
            'distance': self.distance_entry,
        }
        
        self.labels = {
            'saturation': (self.saturation_lbl, "%0.2f"),
            'total_spots': (self.total_spots_lbl,"%d" ),
            'bragg_spots': (self.bragg_spots_lbl, "%d"),
            'ice_rings': (self.ice_rings_lbl, "%d"),
            'resolution': (self.resolution_lbl, "%0.2f"),
            'max_cell': (self.max_cell_lbl, "%0.2f")
        }

        self._load_config()
        self.entries['prefix'].connect('focus-out-event', lambda x,y: self._validate_slug(x, 'test'))
        self.entries['loop_size'].connect('focus-out-event', lambda x,y: self._validate_float(x, 200.0, 20.0, 1000.0))
        self.entries['distance'].connect('focus-out-event', lambda x,y: self._validate_float(x, 250.0, 100.0, 1000.0))
        self.entries['time'].connect('focus-out-event', lambda x,y: self._validate_float(x, 1.0, 0.1, 500))
        
        omega = MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f")
        aperture = ActiveEntry(self.beamline.aperture, 'Beam Aperture', fmt="%0.2f")
        self.param_tbl.attach(omega, 1, 2, 3, 5)
        self.param_tbl.attach(aperture, 2, 4, 3, 5)
        
        sg = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        sg.add_widget(omega)
        sg.add_widget(aperture)
        self.expand_separator.set_expand(True)
        
    def __getattr__(self, key):
        try:
            return super(RasterWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
            
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
        column = gtk.TreeViewColumn("X-pos", renderer, text=model.XPOS)
        treeview.append_column(column)
        
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Y-pos", renderer, text=model.YPOS)
        treeview.append_column(column)

        # column for score
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Score", renderer, text=model.SCORE)
        column.set_sort_column_id(model.SCORE)
        column.set_cell_data_func(renderer, self.__float_format)
        treeview.append_column(column)

        # column for score
        renderer = gtk.CellRendererText()
        renderer.set_fixed_size(14,14)
        column = gtk.TreeViewColumn("", renderer)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(16)
        column.set_cell_data_func(renderer, self.__score_colors)
        treeview.append_column(column)

        return treeview

    def __float_format(self, column, renderer, model, itr):
        value = model.get_value(itr, self.details.SCORE)
        renderer.set_property('text', "%0.2f" % value)

    def __score_colors(self, column, renderer, model, itr):
        value = model.get_value(itr, self.details.SCORE)
        color = self.sample_viewer._grid_colormap.get_hex(value)
        renderer.set_property('cell-background', color)

            
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
                'prefix': 'testgrid',
                'directory': config.SESSION_INFO.get('current_path', config.SESSION_INFO['path']),
                'distance': self.beamline.distance.get_position(),
                'loop_size': 200,
                'aperture': self.beamline.aperture.get(),
                'time': self.beamline.config.get('default_exposure'),
                'delta': 1.0
            }
        self.entries['prefix'].set_text(params['prefix'])
        if params.get('directory') is not None:
            self.entries['directory'].set_current_folder("%s" % params['directory'])
        for key in ['time','loop_size', 'distance']:
            self.entries[key].set_text("%0.1f" % params[key])
            
        if params['mode'] == 'Diffraction':
            self.score_cbx.set_active(0)
        else:
            self.score_cbx.set_active(1)


        
    def get_parameters(self):
        params = {}
        params['prefix']  = self.entries['prefix'].get_text().strip()
        params['directory']   = self.entries['directory'].get_current_folder()
        
        for key in ['time','loop_size','distance']:
            params[key] = float(self.entries[key].get_text())
        params['aperture'] = self.beamline.aperture.get()

        if self.score_cbx.get_active() == 0:
            params['mode'] = 'Diffraction'
        else:
            params['mode'] = 'Fluorescence'
        params['delta'] = 1.0
        return params

    def _load_config(self):
        if not config.SESSION_INFO.get('new', False):
            data = config.load_config(_CONFIG_FILE)
            if data is not None:
                self.set_parameters(data)

    def _save_config(self, parameters):
        config.save_config(_CONFIG_FILE, parameters)

    def on_detail_activated(self, treeview, path, column=None):        
        itr = self.details.get_iter(path)
        info = self.details.get_value(itr, DetailStore.DATA)
        ox, oy = self._result_info['origin']
        angle = self._result_info['angle']
        cell_x = ox - info['xpos']
        cell_y = oy - info['ypos']
        filename = os.path.join(self._result_info['directory'], 
                                self._result_info['details'][info['cell']]['file'])
        gobject.idle_add(self.emit, 'show-image', filename)
        self._center_xyz(angle, cell_x, cell_y)

    def on_detail_selected(self, treeview):
        sel = treeview.get_selection()
        model, itr = sel.get_selected()
        cell = model.get_value(itr, DetailStore.DATA)['cell']
        info = self._result_info['details'][cell]
        for k, wi in self.labels.items():
            w, fmt = wi
            w.set_text(fmt % info[k])

    @async
    def _center_xyz(self, angle, x, y):
        self.beamline.omega.move_to(angle, wait=True)
        if not self.beamline.sample_stage.x.is_busy():
            self.beamline.sample_stage.x.move_to(x, wait=True)
        if not self.beamline.sample_stage.y.is_busy():
            self.beamline.sample_stage.y.move_to(y)
       
    def on_result_activated(self, cell, path, column=None):
        itr = self.results.get_iter_first()
        while itr:
            self.results.set_value(itr, ResultStore.ACTIVE, False)
            itr = self.results.iter_next(itr)
        itr = self.results.get_iter(path)
        self.results.set_value(itr, ResultStore.ACTIVE, True)
        self._result_info = self.results.get_value(itr, ResultStore.DATA)
        self.details.add_items(self._result_info)
        self.beamline.omega.move_to(self._result_info['angle'], wait=False)
        self.sample_viewer.apply_grid_results(self._result_info)
    
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
            if self._status == RASTER_STATE_IDLE:
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
            elif self._status == RASTER_STATE_RUNNING:
                self.pbar.set_text("Pausing ... ")
                self.collector.pause()
            elif self._status == RASTER_STATE_PAUSED:
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
        self._status = RASTER_STATE_IDLE
        self.action_btn.set_label('mxdc-start')
        self.pbar.set_text("Stopped!")
        self.control_box.set_sensitive(True)
        self.results.add_item(self._result_info)
        self.details.add_items(self._result_info)           
        self.result_box.set_sensitive(True)          

    def on_raster_paused(self, obj, state):
        if state:
            self.pbar.set_text("Paused")
            self.action_btn.set_label('mxdc-resume')
            self._status = RASTER_STATE_PAUSED
        else:
            self.action_btn.set_label('mxdc-pause')
            self._status = RASTER_STATE_RUNNING        
        self.action_btn.set_sensitive(True)
        
    def on_raster_started(self, obj):
        self.control_box.set_sensitive(False)
        self.start_time = time.time()
        self.action_btn.set_label('mxdc-pause')
        self.stop_btn.set_sensitive(True)
        self.pbar.set_fraction(0.0)
        self.action_btn.set_sensitive(True)
        self._status = RASTER_STATE_RUNNING
        
        # Demo grid scores based on size
        # self._scores_for_demo = _demo_scores(self._result_info['size'])
    
    def on_raster_completed(self, obj):
        self.stop_btn.set_sensitive(False)
        self.action_btn.set_label('mxdc-start')
        self.control_box.set_sensitive(True)
        self._status = RASTER_STATE_IDLE
        self.results.add_item(self._result_info)
        self.details.add_items(self._result_info)
        self.result_box.set_sensitive(True)          
        
    def on_new_result(self, obj, cell, results):
        results['saturation'] = results['saturation'][1]
        score = _score_diff(results)
        
        # demo override
        # score = self._scores_for_demo[cell[0], cell[1]]

        self.sample_viewer.add_grid_score(cell, score)
        self._result_info['scores'][cell] = score
        self._result_info['details'][cell] = results
        
        
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
    
    if not results:
        return 0.0
    
    #resolution = max(results['resolution'], results['alt_resolution'])
    bragg = results['bragg_spots']
    ice = 1/(1.0 + results['ice_rings'])
    saturation = results['saturation']
    sc_x = numpy.array([bragg, saturation, ice])
    sc_w = numpy.array([5, 10, 0.2])
    score = numpy.exp((sc_w*numpy.log(sc_x)).sum()/sc_w.sum())
        
    return score
