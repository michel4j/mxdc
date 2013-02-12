
from bcm.beamline.mx import IBeamline
from bcm.utils import lims_tools
from bcm.utils.log import get_module_logger
from datetime import datetime
from matplotlib.dates import date2num
from mxdc.utils import gui
from mxdc.widgets import dialogs, misc
from mxdc.widgets.hcviewer import HCViewer
from mxdc.widgets.plotter import Plotter
from mxdc.widgets.ptzviewer import AxisViewer
from mxdc.widgets.sampleloader import DewarLoader, STATUS_NOT_LOADED, STATUS_LOADED
from mxdc.widgets.samplepicker import SamplePicker
from mxdc.widgets.sampleviewer import SampleViewer
from twisted.python.components import globalRegistry
import gobject
import gtk
import os


_logger = get_module_logger('mxdc.samplemanager')

_HCPLOT_INFO = {
    'temps': {'title': 'Temperature', 'units': 'C', 'color': 'm'},
    'drops': {'title': 'Drop Size', 'units': 'um', 'color': 'c'},
    'relhs': {'title': 'Relative Humidity', 'units': 'h', 'color': 'b'}
}

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class SampleManager(gtk.Alignment):
    __gsignals__ = {
        'samples-changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'active-sample': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
        'sample-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }    
    def __init__(self):
        gtk.Alignment.__init__(self, 0, 0, 1, 1)
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'sample_widget'), 
                                  'sample_widget')

        self._switching_hc = False
        self.hc1_active = False
        self._plot_init = False
        self._plot_paused = False
        self._create_widgets()

    
    def __getattr__(self, key):
        try:
            return super(SampleManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_samples_changed(self, data):
        pass

    def do_sample_selected(self, data):
        pass
    
    def do_active_sample(self, data):
        pass
    
    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
        
        # make video and cryo notebooks same vertical size
        self._szgrp1 = gtk.SizeGroup(gtk.SIZE_GROUP_VERTICAL)
        self._szgrp1.add_widget(self.loader_frame)
        self._szgrp1.add_widget(self.robot_frame)
            
        # video, automounter, cryojet, dewar loader 
        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.hutch_video)
        self.dewar_loader = DewarLoader()
        self.cryo_controller = misc.CryojetWidget(self.beamline.cryojet)
        self.sample_picker = SamplePicker()
        
        self.plotter = Plotter(xformat='%g', loop=True, buffer_size=1200, dpi=72)

        def _mk_lbl(txt):
            lbl = gtk.Label(txt)
            lbl.set_padding(6,0)
            return lbl
        
        self.video_ntbk.append_page(self.sample_viewer, tab_label=_mk_lbl('Sample'))
        self.video_ntbk.append_page(self.hutch_viewer, tab_label=_mk_lbl('Hutch'))
        self.video_ntbk.connect('realize', lambda x: self.video_ntbk.set_current_page(0))
        
        self.cryo_ntbk.append_page(self.cryo_controller, tab_label=_mk_lbl('Cryojet Stream'))
        self.cryo_ntbk.connect('realize', lambda x: self.cryo_ntbk.set_current_page(0))

        self.hc_data = None        
        if 'humidifier' in self.beamline.registry:
            self.hc_viewer = HCViewer()
            self.hc = self.beamline.humidifier        
        
            self.video_ntbk.append_page(self.hc_viewer, tab_label=_mk_lbl('Humidity Control'))
            self.video_ntbk.connect('switch-page', self.on_tab_change)
            self.cryo_ntbk.append_page(self.plotter, tab_label=_mk_lbl('Humidity Control'))
            self.cryo_ntbk.connect('switch-page', self.on_tab_change)
            self.hc_viewer.connect('plot-changed', self.on_plot_change)
            self.hc_viewer.connect('plot-paused', self.on_pause)
            self.hc_viewer.connect('plot-cleared', self.on_clear)
                
            self.beamline.humidifier.connect('active', self.on_hc1_active)
        
        self.robot_frame.add(self.sample_picker)    
        self.loader_frame.add(self.dewar_loader)
        self.add(self.sample_widget)
        self.dewar_loader.lims_btn.connect('clicked', self.on_import_lims)
        self.dewar_loader.connect('samples-changed', self.on_samples_changed)
        self.dewar_loader.connect('sample-selected', self.on_sample_selected)
        self.sample_picker.connect('pin-hover', self.on_sample_hover)
        self.beamline.automounter.connect('mounted', self.on_sample_mounted)
        self.beamline.manualmounter.connect('mounted', self.on_sample_mounted, False)
  
    def on_samples_changed(self, obj):
        if self.beamline.automounter.is_mounted():
            self.active_sample = self.dewar_loader.find_crystal(self.beamline.automounter._mounted_port) or {}
            gobject.idle_add(self.emit, 'active-sample', self.active_sample)        
        gobject.idle_add(self.emit, 'samples-changed', self.dewar_loader)

    def update_data(self, sample=None):
        self.dewar_loader.mount_widget.update_data(sample)

    def on_sample_hover(self, obj, cont, port):
        if port is not None:
            xtl = self.dewar_loader.find_crystal(port=port)
            if xtl is not None:
                obj.show_info(xtl['name'])
        else:
            obj.hide_info()

    
    def on_sample_mounted(self, obj, mount_info, auto=True):
        if auto:
            if mount_info is not None: # sample mounted
                port, barcode = mount_info
                if barcode.strip() != '': # find crystal in database by barcode one was detected
                    xtl = self.dewar_loader.find_crystal(barcode=barcode)
                    if xtl is not None:
                        if xtl['port'] != port:
                            header = 'Barcode Mismatch'
                            subhead = 'The observed barcode read by the automounter is different from'
                            subhead += 'the expected one. The barcode will be trusted rather than the port.'
                            dialogs.warning(header, subhead)
                    else:
                        xtl =  self.dewar_loader.find_crystal(port=port)
                else: # if barcode is not read correctly or none exists, use port
                    xtl =  self.dewar_loader.find_crystal(port=port)
                gobject.idle_add(self.emit, 'active-sample', xtl)
    
            else:   # sample dismounted
                gobject.idle_add(self.emit, 'active-sample', None)
        else:
            gobject.idle_add(self.emit, 'active-sample', mount_info)
            
    def on_sample_selected(self, obj, crystal):
        
        if crystal.get('load_status', STATUS_NOT_LOADED) == STATUS_LOADED:
            if self.beamline.automounter.is_mountable(crystal['port']):
                self.sample_picker.pick_port(crystal['port'])
                gobject.idle_add(self.emit, 'sample-selected', crystal)
            else:
                self.sample_picker.pick_port(None)
                gobject.idle_add(self.emit, 'sample-selected', {})
        else:
            self.sample_picker.pick_port(None)
            gobject.idle_add(self.emit, 'sample-selected', crystal)

    def update_active_sample(self, sample=None):
        # send updated parameters to runs
        if sample is None:
            self.active_sample = {}
        else:
            self.active_sample = sample
        self.dewar_loader.mount_widget.update_active_sample(self.active_sample)
    
    def update_selected(self, sample=None):
        self.dewar_loader.mount_widget.update_selected(sample)
    
    def get_database(self):
        return self.dewar_loader.samples_database

    def on_import_lims(self, obj):
        reply = lims_tools.get_onsite_samples(self.beamline)
        if reply.get('error') is not None:
            header = 'Error Connecting to the LIMS'
            subhead = 'Containers and Samples could not be imported.'
            details = reply['error'].get('message')
            dialogs.error(header, subhead, details=details)
        else:
            self.dewar_loader.import_lims(reply)
        
    def on_hc1_active(self, obj, active):
        self.hc1_active = active
        if active:
            if self.hc_data is None: self.reset_data()
            self.tupdate = self.hc.temperature.connect('changed', self.on_new_data, 'temps')
            self.dupdate = self.hc.drop_size.connect('changed', self.on_new_data, 'drops')
            self.hupdate = self.hc.humidity.connect('changed', self.on_new_data, 'relhs')
            self.redraw_plot()
        else:
            self.hc.temperature.disconnect(self.tupdate)
            self.hc.drop_size.disconnect(self.dupdate)
            self.hc.humidity.disconnect(self.hupdate)
            
    def reset_data(self):
        pix_size = self.beamline.sample_video.resolution * 1000
        self.hc_data = {'temps': [(datetime.now(), date2num(datetime.now()), self.hc.temperature.get())], 
                     'drops': [(datetime.now(), date2num(datetime.now()), self.hc.drop_size.get() * pix_size)], 
                     'relhs': [(datetime.now(), date2num(datetime.now()), self.hc.humidity.get())]}

    def on_new_data(self, pv, state, key=None):
        if len(self.hc_data[key]):
            self.hc_data[key].append((datetime.now(), date2num(datetime.now()), self.hc_data[key][-1][2]))
        if key in ['drops']:
            pix_size = self.beamline.sample_video.resolution * 1000
            state = state * pix_size
        self.hc_data[key].append((datetime.now(), date2num(datetime.now()), state))

        if len(self.hc_data[key]) > 1000:
            self.hc_data[key].pop(0)
        self.plot_new_points(key)
            
    def on_tab_change(self, obj, pointer, page_num):
        if not self._switching_hc:
            self._switching_hc = True
            if obj is self.video_ntbk and page_num == 2 and self.cryo_ntbk.get_current_page() != 1:
                self.cryo_ntbk.set_current_page(1)
            elif obj is self.cryo_ntbk and page_num == 1 and self.video_ntbk.get_current_page() != 2:
                self.video_ntbk.set_current_page(2)
            self._switching_hc = False
            
    def on_plot_change(self, obj, widget, state):
        self.redraw_plot(widget, state)

    def on_pause(self, obj, widget, paused):
        self._plot_paused = paused
        if not paused:
            self.redraw_plot()
    
    def on_clear(self, obj, data):
        self.reset_data()
        self.redraw_plot()
        
    def plot_config(self, key):
        now = self.hc_data[key][-1][0]
        xlabels = []
        tot = self.hc_viewer.xtime + 1
        for i in range(tot):
            minutes = ((now.minute + (i-(tot-1)) < 0) and now.minute + (i-(tot-1)) + 60) or (now.minute + (i-(tot-1))) 
            hours = ((minutes - (i-(tot-1)) > 59) and now.hour - 1) or (now.hour)
            time = ( tot > 10 and ( i % 2 and ' ' ) ) or datetime(now.year, now.month, now.day, hours, minutes, now.second)
            xlabels.append(time)
        return (date2num(xlabels[0]), date2num(now), xlabels)
   
    def redraw_plot(self, widget=None, state=True):
        self.plotter.clear()
        self._plot_init = True
        
        if widget is not None:
            if state is True:
                self.pname = 'temps'
            else:
                self.pname = 'drops'
        
        if self.hc_data and self.pname:
            self.add_hc_line(self.pname)
            self.add_hc_line('relhs', 1)

            self.plotter.axis[0].xaxis.grid(True)
            self.plotter.axis[0].yaxis.set_label_coords(-0.12, 0.5)
            if not self.hc1_active:
                self.plot_new_points(self.pname)
        
    def add_hc_line(self, name, ax=0):
        info = _HCPLOT_INFO[name]
        if ax:
            axis = self.plotter.add_axis(info.get('title'))
        else:
            self.plotter.set_labels(x_label='Time', y1_label='%s (%s)' % (info.get('title'), info.get('units')))
            self.plotter.axis[ax].set_title(info.get('title'))  
            self.plotter.axis[ax].yaxis.set_ticks_position('left')
            axis = 0
        xdata = []
        ydata = []
        for point in self.hc_data[name]:
            t, y = point[1:3]
            xdata.append(t)
            ydata.append(y)
        self.plotter.add_line(xdata, ydata, '%s-' % info.get('color'), info.get('title'), axis, redraw=False)
        self.plotter.axis[ax].yaxis.label.set_color(info.get('color'))
        for tl in self.plotter.axis[ax].get_yticklabels():
            tl.set_color(info.get('color'))
        
    def plot_new_points(self, plot):
        if not self._plot_paused or self._plot_init:
            self._plot_init = False
            min_val, max_val, xlabels = self.plot_config(plot)
            t = self.hc_data[plot][-1][1]
            
            # add points to each plot
            if plot == self.pname or plot == 'relhs':
                ry = self.hc_data['relhs'][-1][2]
                py = self.hc_data[self.pname][-1][2]
                self.plotter.add_point(t, py, lin=0, redraw=False, resize=True)
                self.plotter.add_point(t, ry, lin=1, redraw=False)
            
            # tweak formatting before drawing plots
            if len(self.plotter.axis) > 1:
                self.plotter.axis[1].set_ylim((0,100))
            self.plotter.axis[0].set_xlim((min_val, max_val))
            self.plotter.set_time_labels(xlabels, '%H:%M', 1, 10)
            self.plotter.canvas.draw()
        
        
                        
