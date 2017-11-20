import common
import uuid
from datetime import datetime

from gi.repository import Gtk
from mxdc.beamlines.mx import IBeamline
from mxdc.widgets import misc
from mxdc.widgets import ticker
from mxdc.conf import load_cache, save_cache
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui, datatools
from mxdc.engines.humidity import SingleCollector
from mxdc.utils.converter import resol_to_dist
from twisted.python.components import globalRegistry
from samplestore import ISampleStore


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

    def __init__(self, widget):
        super(HumidityController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.collector = SingleCollector()

        self.humidifier = self.beamline.humidifier
        self.labels = {}
        self.limits = {}
        self.formats = {}
        self.entries = {}
        self.plotter = ticker.ChartManager(interval=500, view=240)
        self.setup()
        self.humidifier.connect('active', self.activate)
        self.load_from_cache()

        self.collector.connect('done', self.on_collector_done)
        self.collector.connect('result', self.on_collector_result)
        self.hc_diff_btn.connect('clicked', self.on_collect)

    def load_from_cache(self):
        cache = load_cache('humidity')
        if cache and isinstance(cache, dict):
            self.configure(cache)

    def get_parameters(self):
        info = {}
        for name, details in self.ConfigSpec.items():
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
        for name, details in self.ConfigSpec.items():
            field_type, fmt, conv, default = details
            field_name = '{}_{}_{}'.format(self.ConfigPrefix,name, field_type)
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
        params['name'] = datetime.now().strftime('%y%m%d-%H%M')
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
        print collector, result

    def on_collect(self, button):
        button.set_sensitive(False)
        self.take_snapshot()

    def setup(self):
        self.monitors = [
            common.DeviceMonitor(self.humidifier.dew_point, self.hc_dewpoint_fbk, format='{:0.2f} K'),
            #common.DeviceMonitor(self.humidifier.drop_size, self.hc_dropsize_fbk, format='{:0.0f} px')
        ]
        self.entries = {
            'humidity': misc.ActiveEntry(self.humidifier.humidity, 'Relative Humidity', fmt="%0.2f"),
            'temperature': misc.ActiveEntry(self.humidifier.temperature, 'Temperature', fmt="%0.2f"),
        }
        self.plotter.add_plot(self.humidifier.humidity, 'Relative Humidity', axis=0)
        self.plotter.add_plot(self.humidifier.drop_size, 'Drop Size', axis=1)

        self.hc_control_grid.attach(self.entries['humidity'], 0, 0, 1, 1)
        self.hc_control_grid.attach(self.entries['temperature'], 1, 0, 1, 1)
        self.humidity_box.pack_start(self.plotter.chart, True, True, 0)
        self.hc_zoomout_btn.connect('clicked', self.plotter.zoom_in)
        self.hc_zoomin_btn.connect('clicked', self.plotter.zoom_out)
        self.hc_clear_btn.connect('clicked', self.plotter.clear)
        self.hc_save_btn.connect('clicked', self.plotter.save)
        self.hc_pause_btn.connect('clicked', self.on_pause_btn)
        self.humidity_box.show_all()
        self.widget.samples_stack.add_titled(self.humidity_box, 'humidity', 'Humidity')

    def activate(self, dev, state):
        self.humidity_box.set_sensitive(state)
