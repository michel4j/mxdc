import time
import logging
import os
import numpy

from gi.repository import GLib
from gi.repository import Gtk
from mxdc.utils import gui, misc
from mxdc.widgets import dialogs
from mxdc.widgets.imagewidget import ImageWidget
from mxdc import Registry
from zope.interface import Interface

logger = logging.getLogger(__name__)

MAX_FOLLOW_DURATION = 5


class IImageViewer(Interface):
    """Image Viewer."""

    def queue_frame(filename):
        ...

    def add_frame(filename):
        ...


class ImageViewer(Gtk.Alignment, gui.BuilderMixin):
    gui_roots = {
        'data/image_viewer': ['image_viewer', 'info_dialog', 'frames_pop']
    }
    Formats = {
        'average_intensity': '{:0.2f}',
        'max_intensity': '{:0.0f}',
        'overloads': '{:0.0f}',
        'wavelength': '{:0.4g} Å',
        'delta_angle': '{:0.4g}°',
        'two_theta': '{:0.2g}°',
        'start_angle': '{:0.3g}°',
        'exposure_time': '{:0.4g} s',
        'distance': '{:0.1f} mm',
        'pixel_size': '{:0.4g} mm',
        'detector_size': '{}, {}',
        'beam_center': '{:0.0f}, {:0.0f}',
        'filename': '{}',
        'detector_type': '{}',
    }

    def __init__(self, size=700):
        super(ImageViewer, self).__init__()
        self.setup_gui()
        self.set(0.5, 0.5, 1, 1)
        self.dataset = None
        self.canvas = None
        self.size = size

        self.following = False
        self.follow_timeout = 0
        self.updating = True
        self.collecting = False
        self.icons = {
            'on': 'media-playback-pause-symbolic',
            'off': 'media-playback-start-symbolic',
        }

        self.reflections = []
        self.data_adjustment = Gtk.Adjustment(1, 1, 360, 1, 10, 0)
        self.build_gui()
        Registry.add_utility(IImageViewer, self)

    def build_gui(self):
        self.info_dialog.set_transient_for(dialogs.MAIN_WINDOW)
        self.canvas = ImageWidget(self.size)
        self.frames_scale.set_adjustment(self.data_adjustment)
        self.frames_scale.connect('value-changed', self.on_frames_changed)
        self.frames_scale.connect('change-value', self.on_frames_updated)
        self.frames_close_btn.connect('clicked', self.on_frames_popup_closed)
        self.canvas.connect('image-loaded', self.on_data_loaded)
        self.image_frame.add(self.canvas)
        self.canvas.connect('motion_notify_event', self.on_mouse_motion)

        self.info_btn.connect('clicked', self.on_image_info)
        self.play_btn.connect('clicked', self.on_play)
        self.colorize_tbtn.connect('toggled', self.on_colorize_toggled)
        self.reset_btn.connect('clicked', self.on_reset_filters)

        # signals
        self.open_btn.connect('clicked', self.on_file_open)
        self.save_btn.connect('clicked', self.on_file_save)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.frames_btn.connect('toggled', self.on_frames_toggled)
        self.back_btn.connect('clicked', self.on_go_back, False)
        self.zoom_fit_btn.connect('clicked', self.on_go_back, True)
        self.info_close_btn.connect('clicked', self.on_info_hide)
        self.get_style_context().add_class('image-viewer')
        self.add(self.image_viewer)
        self.show_all()

    def load_reflections(self, filename, hkl=False):
        try:
            if hkl:
                return misc.load_hkl(filename)
            else:
                return misc.load_spots(filename)
        except IOError:
            logger.error('Could not load reflections from %s' % filename)

    def set_collect_mode(self, state=True):
        self.following = False
        self.collecting = state
        if self.collecting:
            logger.debug('Monitoring dataset images during collection ...')
            self.updating = True
            status = 'on'
        else:
            status = 'off'
        self.play_btn.set_icon_name(self.icons[status])

    def on_reset_filters(self, widget):
        self.canvas.reset_filters()
        self.canvas.set_reflections(None)

    def on_go_back(self, widget, full):
        self.canvas.go_back(full)
        return True

    def on_mouse_motion(self, widget, event):
        ix, iy, ires, ivalue = self.canvas.get_position(event.x, event.y)
        self.info_pos.set_markup("<tt><small>X:{0:6}\nY:{1:6}</small></tt>".format(ix, iy))
        self.info_data.set_markup("<tt><small>I:{0:6}\nÅ:{1:6.2f}</small></tt>".format(ivalue, ires))
        self.info_pos.set_alignment(1, 0.5)
        self.info_data.set_alignment(1, 0.5)

    def on_data_loaded(self, obj=None):
        self.dataset = self.canvas.get_image_info()
        directory = self.dataset.header.get('dataset', {}).get('directory')
        self.reset_frames()
        if directory:
            os.chdir(self.dataset.header['dataset']['directory'])

        self.save_btn.set_sensitive(True)
        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.colorize_tbtn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.play_btn.set_sensitive(True)
        self.info_btn.set_sensitive(True)
        self.prev_btn.set_sensitive(True)
        self.next_btn.set_sensitive(True)

        info = self.dataset.header
        for name, fmt in list(self.Formats.items()):
            field_name = '{}_lbl'.format(name)
            field = getattr(self, field_name, None)
            if field and name in info:
                if isinstance(info[name], (tuple, list)):
                    txt = fmt.format(*info[name])
                else:
                    txt = fmt.format(info[name])
                field.set_text(txt)
        self.follow_timeout = time.time() + MAX_FOLLOW_DURATION

    def open_frame(self, filename):
        # select spots and display for current image
        if len(self.reflections) > 0:
            self.canvas.set_reflections(None)
        self.canvas.open(filename)

    def show_frame(self, frame):
        if self.updating:
            self.canvas.show_frame(frame)

    def reset_frames(self):
        sequence = self.dataset.header.get('dataset', {}).get('sequence', [])
        if len(sequence):
            self.frames_btn.set_sensitive(True)
            self.data_adjustment.set_lower(sequence[0])
            self.data_adjustment.set_upper(sequence[-1])
        else:
            self.frames_btn.set_sensitive(False)

        self.frames_scale.set_value(self.dataset.header['frame_number'])
        values = numpy.unique(numpy.linspace(sequence[0], sequence[-1], 5).astype(int))
        self.frames_scale.clear_marks()
        for value in values:
            self.frames_scale.add_mark(value, Gtk.PositionType.BOTTOM, f'{value}')

    def follow_frames(self):
        self.canvas.load_next()
        if time.time() > self.follow_timeout:
            self.following = False
            status = 'off'
            self.play_btn.set_icon_name(self.icons[status])
        return self.following

    def on_image_info(self, obj):
        self.on_data_loaded()
        self.info_dialog.show_all()

    def on_info_hide(self, obj):
        self.info_dialog.hide()

    def on_next_frame(self, widget):
        self.canvas.load_next()

    def on_prev_frame(self, widget):
        self.canvas.load_prev()

    def on_file_open(self, widget):
        filename, flt = dialogs.select_open_image(
            parent=self.get_toplevel(), default_folder=os.getcwd()
        )
        if filename and os.path.isfile(filename):
            self.following = False
            os.chdir(os.path.dirname(os.path.abspath(filename)))
            file_type = flt.get_name()
            if file_type in ['XDS Spot files', 'XDS ASCII file']:
                refl = self.load_reflections(filename, hkl=(file_type == 'XDS ASCII file'))
                self.canvas.set_reflections(refl)
                if self.canvas.image_loaded:
                    GLib.idle_add(self.canvas.queue_draw)
            else:
                self.open_frame(os.path.abspath(filename))

    def on_file_save(self, widget):
        filename, flt = dialogs.select_save_file("Save display to file")
        if filename:
            path = os.path.abspath(filename)
            self.canvas.save_surface(path)

    def on_colorize_toggled(self, button):
        self.canvas.colorize(self.colorize_tbtn.get_active())

    def on_play(self, widget):
        if self.collecting:
            self.following = False
            self.updating = not self.updating
            if self.updating:
                status = "on"
                self.canvas.resume()
            else:
                status = "off"
                self.canvas.pause()
        else:
            self.following = not self.following
            if self.following:
                status = "on"
                logger.debug('Replaying the dataset images ...')
                GLib.timeout_add(100, self.follow_frames)
                self.follow_timeout = time.time() + MAX_FOLLOW_DURATION
            else:
                logger.debug('Done replaying the dataset images ...')
                status = "off"
        self.play_btn.set_icon_name(self.icons[status])

    def on_frames_toggled(self, widget):
        if self.frames_btn.get_active():
            # configure the marks
            self.reset_frames()

            # position the popup
            window = dialogs.MAIN_WINDOW
            ox, oy = window.get_position()
            geom = self.canvas.get_window().get_geometry()
            cx = ox + geom.x + geom.width / 2 - 150
            cy = oy + geom.y + geom.height - 50
            self.frames_pop.move(cx, cy)
            self.frames_pop.set_transient_for(window)
            self.frames_pop.show_all()
        else:
            self.frames_pop.hide()

    def on_frames_popup_closed(self, widget):
        self.frames_btn.set_active(False)
        self.frames_pop.hide()

    def on_frames_changed(self, scale):
        pass

    def on_frames_updated(self, scale, scroll, value):
        sequence = self.dataset.header.get('dataset', {}).get('sequence', [])
        frame_number = int(value)
        if frame_number in sequence:
            self.canvas.load_frame(frame_number)
