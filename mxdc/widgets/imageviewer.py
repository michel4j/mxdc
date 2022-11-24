import time
import logging
import os

from gi.repository import GLib
from gi.repository import Gtk
from mxdc.utils import gui, misc
from mxdc.widgets import dialogs
from mxdc.widgets.imagewidget import ImageWidget
from mxdc import Registry
from zope.interface import Interface

logger = logging.getLogger(__name__)

MAX_FOLLOW_DURATION = 20


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
        self.collecting = False
        self.following_id = None
        self.reflections = []

        self.build_gui()
        Registry.add_utility(IImageViewer, self)

    def build_gui(self):
        self.info_dialog.set_transient_for(dialogs.MAIN_WINDOW)
        self.canvas = ImageWidget(self.size)
        self.canvas.connect('image-loaded', self.on_data_loaded)
        self.image_frame.add(self.canvas)
        self.canvas.connect('motion_notify_event', self.on_mouse_motion)

        self.info_btn.connect('clicked', self.on_image_info)
        self.follow_tbtn.connect('clicked', self.on_follow_toggled)
        self.colorize_tbtn.connect('toggled', self.on_colorize_toggled)
        self.reset_btn.connect('clicked', self.on_reset_filters)

        # signals
        self.open_btn.connect('clicked', self.on_file_open)
        self.save_btn.connect('clicked', self.on_file_save)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
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
        self.collecting = state
        self.follow_tbtn.set_active(state)
        if state:
            self.canvas.resume()
        else:
            self.canvas.pause()

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
        if self.dataset.header.get('dataset'):
            os.chdir(self.dataset.header['dataset']['directory'])

        self.save_btn.set_sensitive(True)
        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.colorize_tbtn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.follow_tbtn.set_sensitive(True)
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

    def open_frame(self, filename):
        # select spots and display for current image
        if len(self.reflections) > 0:
            self.canvas.set_reflections(None)
        self.canvas.open(filename)

    def show_frame(self, frame):
        self.canvas.show_frame(frame)

    def follow_frames(self):
        self.canvas.load_next()
        return self.follow_tbtn.get_active()

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

    def on_follow_toggled(self, widget):
        if widget.get_active():
            self.following_id = GLib.timeout_add(100, self.follow_frames)
            self.canvas.resume()
        elif self.following_id:
            GLib.source_remove(self.following_id)
            self.following_id = None
            self.canvas.pause()

