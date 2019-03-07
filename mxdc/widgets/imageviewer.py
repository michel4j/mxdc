# -*- coding: UTF8 -*-

import glob
import logging
import os
import re

import numpy
from gi.repository import GObject
from gi.repository import Gtk
from mxdc.utils import gui
from mxdc.widgets import dialogs
from mxdc.widgets.imagewidget import ImageWidget
from twisted.python.components import globalRegistry
from zope.interface import Interface

logger = logging.getLogger(__name__)

FILE_PATTERN = re.compile('^(?P<base>[\w-]+\.?)(?<!\d)(?P<num>\d{3,4})(?P<ext>\.?[\w.]+)?$')


class IImageViewer(Interface):
    """Image Viewer."""

    def queue_frame(filename):
        pass

    def add_frame(filename):
        pass


class ImageViewer(Gtk.Alignment, gui.BuilderMixin):
    gui_roots = {
        'data/image_viewer': ['image_viewer', 'info_dialog']
    }
    Formats = {
        'average_intensity': '{:0.0f}',
        'max_intensity': '{:0.0f}',
        'overloads': '{:0.0f}',
        'wavelength': u'{:0.4f} \u212B',
        'delta_angle': '{:0.2f} deg',
        'two_theta': '{:0.1f} deg',
        'start_angle': '{:0.2f} deg',
        'exposure_time': '{:0.2f} s',
        'distance': '{:0.1f} mm',
        'pixel_size': '{:0.4f} um',
        'detector_size': '{}, {}',
        'beam_center': '{:0.0f}, {:0.0f}',
        'filename': '{}',
        'detector_type': '{}',
    }

    def __init__(self, size=512):
        super(ImageViewer, self).__init__()
        self.setup_gui()
        self.set(0.5, 0.5, 1, 1)
        self.dataset = None
        self._canvas_size = size
        self._brightness = 1.0
        self.file_template = None
        self._following = False
        self._collecting = False
        self._br_hide_id = None
        self._co_hide_id = None
        self._cl_hide_id = None
        self._follow_id = None

        self._dataset_frames = []
        self._dataset_pos = 0

        self._last_queued = ''
        self.directory = None
        self.filename = None
        self.all_spots = []
        self.build_gui()
        globalRegistry.register([], IImageViewer, '', self)

    def build_gui(self):
        self.info_dialog.set_transient_for(dialogs.MAIN_WINDOW)
        self.image_canvas = ImageWidget(self._canvas_size)
        self.image_canvas.connect('image-loaded', self.on_data_loaded)
        self.image_frame.add(self.image_canvas)
        self.image_canvas.connect('motion_notify_event', self.on_mouse_motion)

        self.info_btn.connect('clicked', self.on_image_info)
        self.follow_tbtn.connect('toggled', self.on_follow_toggled)

        self.colorize_tbtn.connect('toggled', self.on_colorize_toggled)

        self.reset_btn.connect('clicked', self.on_reset_filters)

        # signals
        self.open_btn.connect('clicked', self.on_file_open)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.back_btn.connect('clicked', self.on_go_back, False)
        self.zoom_fit_btn.connect('clicked', self.on_go_back, True)
        self.info_close_btn.connect('clicked', self.on_info_hide)

        self.add(self.image_viewer)
        self.show_all()

    def _load_spots(self, filename):
        try:
            self.all_spots = numpy.loadtxt(filename)
        except:
            logger.error('Could not load spots from %s' % filename)

    def _select_spots(self, spots):
        def _zeros(a):
            for v in a:
                if abs(v) > 0.01:
                    return False
            return True

        indexed = [sp for sp in spots if not _zeros(sp[4:])]
        unindexed = [sp for sp in spots if _zeros(sp[4:])]
        return indexed, unindexed

    def _select_image_spots(self, spots):
        image_spots = [sp for sp in spots if abs(self.frame_number - sp[2]) <= 1]
        return image_spots

    def open_image(self, filename):
        # select spots and display for current image
        if len(self.all_spots) > 0:
            image_spots = self._select_image_spots(self.all_spots)
            indexed, unindexed = self._select_spots(image_spots)
            self.image_canvas.set_spots(indexed, unindexed)

        logger.info("Loading image {}".format(filename))
        self.image_canvas.open(filename)

    def set_collect_mode(self, state=True):
        self._collecting = state
        self.follow_tbtn.set_active(state)

    def on_reset_filters(self, widget):
        self.image_canvas.reset_filters()

    def on_go_back(self, widget, full):
        self.image_canvas.go_back(full)
        return True

    def on_mouse_motion(self, widget, event):
        ix, iy, ires, ivalue = self.image_canvas.get_position(event.x, event.y)
        self.info_pos.set_markup("<tt><small>X:{0:5}\nY:{1:5}</small></tt>".format(ix, iy))
        self.info_data.set_markup("<tt><small>I:{0:5}\nÅ:{1:5.1f}</small></tt>".format(ivalue, ires))
        self.info_pos.set_alignment(1, 0.5)
        self.info_data.set_alignment(1, 0.5)

    def on_data_loaded(self, obj=None):
        color = 'DarkSlateGray'  # colors.Category.CAT20C[0]
        dataset = self.image_canvas.get_image_info()
        if dataset.header.get('dataset'):
            self.directory = dataset.header['dataset']['directory']

        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.colorize_tbtn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.follow_tbtn.set_sensitive(True)
        self.info_btn.set_sensitive(True)
        self.prev_btn.set_sensitive(True)
        self.next_btn.set_sensitive(True)

        info = dataset.header

        for name, format in self.Formats.items():
            field_name = '{}_lbl'.format(name)
            field = getattr(self, field_name, None)
            if field and name in info:
                if isinstance(info[name], (tuple, list)):
                    txt = u'<span color="{}"><tt>{}</tt></span>'.format(
                        color, format.format(*info[name])
                    )
                else:
                    txt = u'<span color="{}"><tt>{}</tt></span>'.format(
                        color, format.format(info[name])
                    )
                field.set_markup(txt)

    def open_frame(self, filename):
        self.image_canvas.open(filename)

    def _replay_frames(self):
        if self._following and 0 <= self._dataset_pos + 1 < len(self._dataset_frames):
            self.image_canvas.open(self._dataset_frames[self._dataset_pos + 1])
            return True
        else:
            return False

    def on_image_info(self, obj):
        self.on_data_loaded()
        self.info_dialog.show_all()

    def on_info_hide(self, obj):
        self.info_dialog.hide()

    def on_next_frame(self, widget):
        dataset = self.image_canvas.get_image_info()
        dataset.next_frame()

    def on_prev_frame(self, widget):
        dataset = self.image_canvas.get_image_info()
        dataset.prev_frame()

    def on_file_open(self, widget):
        filename, flt = dialogs.select_open_image(parent=self.get_toplevel(),
                                                  default_folder=self.directory)
        if filename is not None and os.path.isfile(filename):
            name, ext = os.path.splitext(filename)
            if flt.get_name() == 'XDS Spot files' or name == 'SPOT' or ext == '.XDS':
                self._load_spots(filename)
                # if spot information is available  and an image is loaded display it
                if self.image_canvas.image_loaded:
                    image_spots = self._select_image_spots(self.all_spots)
                    indexed, unindexed = self._select_spots(image_spots)
                    self.image_canvas.set_spots(indexed, unindexed)
                    GObject.idle_add(self.image_canvas.queue_draw)
            else:
                self.open_image(filename)

    def on_colorize_toggled(self, button):
        self.image_canvas.colorize(self.colorize_tbtn.get_active())

    def on_follow_toggled(self, widget):
        self._following = widget.get_active()
        if not self._collecting:
            GObject.timeout_add(2500, self._replay_frames)
        return True
