import common

from gi.repository import Gtk
from mxdc.beamline.mx import IBeamline
from mxdc.widgets import misc
from mxdc.widgets import ticker

from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry

_logger = get_module_logger(__name__)


class HumidityController(object):
    def __init__(self, widget):
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.humidifier = self.beamline.humidifier
        self.labels = {}
        self.limits = {}
        self.formats = {}
        self.entries = {}
        self.plotter = ticker.ChartManager(interval=500, view=240)
        self.setup()

    def on_pause_btn(self, *args, **kwargs):
        if self.plotter.is_paused():
            self.plotter.resume()
            self.widget.hc_pause_icon.set_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON)
        else:
            self.plotter.pause()
            self.widget.hc_pause_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)

    def setup(self):
        self.monitors = [
            common.DeviceMonitor(self.humidifier.dew_point, self.widget.hc_dewpoint_fbk, format='{:0.2f} K'),
            #common.DeviceMonitor(self.humidifier.drop_size, self.widget.hc_dropsize_fbk, format='{:0.0f} px')
        ]
        self.entries = {
            'humidity': misc.ActiveEntry(self.humidifier.humidity, 'Relative Humidity', fmt="%0.2f"),
            'temperature': misc.ActiveEntry(self.humidifier.temperature, 'Temperature', fmt="%0.2f"),
        }
        self.plotter.add_plot(self.humidifier.humidity, 'Relative Humidity', axis=0)
        self.plotter.add_plot(self.humidifier.drop_size, 'Drop Size', axis=1)

        self.widget.hc_control_grid.attach(self.entries['humidity'], 0, 0, 1, 1)
        self.widget.hc_control_grid.attach(self.entries['temperature'], 1, 0, 1, 1)
        self.widget.humidity_box.pack_start(self.plotter.chart, True, True, 0)
        self.widget.hc_zoomout_btn.connect('clicked', self.plotter.zoom_in)
        self.widget.hc_zoomin_btn.connect('clicked', self.plotter.zoom_out)
        self.widget.hc_clear_btn.connect('clicked', self.plotter.clear)
        self.widget.hc_save_btn.connect('clicked', self.plotter.save)
        self.widget.hc_pause_btn.connect('clicked', self.on_pause_btn)

