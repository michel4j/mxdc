import uuid
from datetime import datetime

import numpy
from gi.repository import Gtk
from mxdc import Registry

from mxdc.beamlines.mx import IBeamline
from mxdc.conf import load_cache, save_cache
from mxdc.devices.misc import SimPositioner
from mxdc.engines.humidity import SingleCollector
from mxdc.utils import gui, datatools
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc
from mxdc.widgets import ticker
from . import common
from .samplestore import ISampleStore

logger = get_module_logger(__name__)


class HumidityController(gui.Builder):
    gui_roots = {
        'data/humidity': ['humidity_box']
    }

    ConfigSpec = {
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'resolution': ['entry', '{:0.3g}', float, 3.0],
    }
    ConfigPrefix = 'hc'
    PLOTS = {
        'drop': 'Drop Size',
        'cell': 'Maximum Cell Dimension',
        'score': 'Diffraction Score',
        'resolution': 'Diffraction Resolution'
    }

    def __init__(self, widget):
        super(HumidityController, self).__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = SingleCollector()

        self.humidifier = self.beamline.humidifier
        self.labels = {}
        self.limits = {}
        self.formats = {}
        self.entries = {}
        self.diff_devices = {
            'cell': SimPositioner('Max Cell Dimension', pos=numpy.nan, delay=False, noise=0),
            'score': SimPositioner('Diffraction Score', pos=numpy.nan, delay=False, noise=0),
            'resolution': SimPositioner('Diffraction Resolution', pos=numpy.nan, delay=False, noise=0),
        }
        self.plotter = ticker.ChartManager(interval=500, view=240)
        self.setup()
        self.humidifier.connect('active', self.activate)
        self.load_from_cache()

        self.collector.connect('done', self.on_collector_done)
        self.collector.connect('result', self.on_collector_result)
        self.hc_diff_btn.connect('clicked', self.on_collect)

        self.plot_options = {
            'cell': self.hc_cell_option,
            'drop': self.hc_drop_option,
            'score': self.hc_score_option,
            'resolution': self.hc_resolution_option
        }
        for key, option in list(self.plot_options.items()):
            option.connect('toggled', self.on_plot_option)

    def load_from_cache(self):
        cache = load_cache('humidity')
        if cache and isinstance(cache, dict):
            self.configure(cache)

    def get_parameters(self):
        info = {}
        for name, details in list(self.ConfigSpec.items()):
            field_type, fmt, conv, default = details
            field_name = '{}_{}_{}'.format(self.ConfigPrefix, name, field_type)
            field = getattr(self, field_name)
            raw_value = default
            if field_type == 'entry':
                raw_value = field.get_text()
            elif field_type == 'switch':
                raw_value = field.get_active()
            elif field_type == 'cbox':
                raw_value = field.get_active_id()
            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default
            info[name] = value
        return info

    def configure(self, info):
        if not self.ConfigSpec: return
        for name, details in list(self.ConfigSpec.items()):
            field_type, fmt, conv, default = details
            field_name = '{}_{}_{}'.format(self.ConfigPrefix, name, field_type)
            value = info.get(name, default)
            field = getattr(self, field_name, None)
            if not field: continue
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'check':
                field.set_active(value)
            elif field_type == 'spin':
                field.set_value(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            try:
                conv(value)
                field.get_style_context().remove_class('error')
            except (TypeError, ValueError):
                field.get_style_context().add_class('error')

    def take_snapshot(self):
        params = self.get_parameters()
        save_cache(params, 'humidity')

        params['angle'] = self.beamline.omega.get_position()
        params['energy'] = self.beamline.energy.get_position()
        params['distance'] = resol_to_dist(params['resolution'], self.beamline.detector.mm_size, params['energy'])
        params['attenuation'] = self.beamline.attenuator.get()
        params['delta'] = 1.0
        params['uuid'] = str(uuid.uuid4())
        params['name'] = datetime.now().strftime('%y%m%d-%H%M%S')
        params['activity'] = 'humidity'
        params = datatools.update_for_sample(params, self.sample_store.get_current())

        self.collector.configure(params)
        self.collector.start()

    def on_pause_btn(self, *args, **kwargs):
        if self.plotter.is_paused():
            self.plotter.resume()
            self.hc_pause_icon.set_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON)
        else:
            self.plotter.pause()
            self.hc_pause_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)

    def on_collector_done(self, *args, **kwargs):
        self.hc_diff_btn.set_sensitive(True)

    def on_collector_result(self, collector, result):
        if result:
            resolution = result['resolution']
            cell = result['max_cell']
            bragg = result['bragg_spots']
            ice = 1 / (1.0 + result['ice_rings'])
            saturation = result['saturation'][1]
            sc_x = numpy.array([bragg, saturation, ice])
            sc_w = numpy.array([5, 10, 0.2])
            score = numpy.exp((sc_w * numpy.log(sc_x)).sum() / sc_w.sum())
            self.diff_devices['cell'].set_position(cell)
            self.diff_devices['resolution'].set_position(resolution)
            self.diff_devices['score'].set_position(score)
        else:
            self.diff_devices['score'].set_position(0.0)

    def on_collect(self, button):
        button.set_sensitive(False)
        self.take_snapshot()

    def on_plot_option(self, button):
        active = 'drop'
        for key, option in list(self.plot_options.items()):
            if option.get_active():
                active = key
                break
        self.plotter.select_active(self.PLOTS[active])

    def setup(self):
        self.monitors = [
            common.DeviceMonitor(self.humidifier.dew_point, self.hc_dewpoint_fbk, format='{:0.2f} K'),
            # common.DeviceMonitor(self.humidifier.drop_size, self.hc_dropsize_fbk, format='{:0.0f} px')
        ]
        self.entries = {
            'humidity': misc.ActiveEntry(self.humidifier.humidity, 'Relative Humidity', fmt="%0.2f"),
            'temperature': misc.ActiveEntry(self.humidifier.temperature, 'Temperature', fmt="%0.2f"),
        }
        self.plotter.add_plot(self.humidifier.humidity, 'Relative Humidity', axis=0)
        for name, device in list(self.diff_devices.items()):
            self.plotter.add_plot(device, self.PLOTS[name], axis=1, alternate=True)
        self.plotter.add_plot(self.humidifier.drop_size, self.PLOTS['drop'], axis=1, alternate=True)

        self.hc_control_grid.attach(self.entries['humidity'], 0, 0, 1, 1)
        self.hc_control_grid.attach(self.entries['temperature'], 1, 0, 1, 1)
        self.humidity_box.pack_start(self.plotter.chart, True, True, 0)
        self.hc_zoomout_btn.connect('clicked', self.plotter.zoom_in)
        self.hc_zoomin_btn.connect('clicked', self.plotter.zoom_out)
        self.hc_clear_btn.connect('clicked', self.plotter.clear)
        self.hc_save_btn.connect('clicked', self.plotter.save)
        self.hc_pause_btn.connect('clicked', self.on_pause_btn)
        self.humidity_box.show_all()
        if hasattr(self.widget, 'samples_stack'):
            self.widget.samples_stack.add_titled(self.humidity_box, 'humidity', 'Humidity')
        else:
            self.widget.main_stack.add_titled(self.humidity_box, 'humidity', 'Humidity')

    def activate(self, dev, state):
        self.humidity_box.set_sensitive(state)
