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


class ImageViewer(Gtk.EventBox, gui.BuilderMixin):
    gui_roots = {
        'data/image_viewer': ['image_viewer', 'info_dialog', 'frames_pop']
    }
    Formats = {
        'average': '{:0.2f}',
        'maximum': '{:0.0f}',
        'cutoff_value': '{:0.0f}',
        'overloads': '{:0.0f}',
        'wavelength': '{:0.4g} Å',
        'delta_angle': '{:0.4g}°',
        'two_theta': '{:0.2g}°',
        'start_angle': '{:0.5g}°',
        'exposure': '{:0.4g} s',
        'distance': '{:0.1f} mm',
        'pixel_size': '{:0.4g} mm',
        'size': '{x}, {y}',
        'center': '{x:0.0f}, {y:0.0f}',
        'detector': '{}',
    }

    def __init__(self, size=700):
        super(ImageViewer, self).__init__()
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.setup_gui()

        self.frame = None
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

        self.data_adjustment = Gtk.Adjustment(1, 1, 360, 1, 10, 0)
        self.build_gui()
        Registry.add_utility(IImageViewer, self)

    def build_gui(self):
        self.info_dialog.set_transient_for(dialogs.MAIN_WINDOW)
        self.get_style_context().add_class('image-viewer')
        self.canvas = ImageWidget(self.size)
        self.image_frame.add(self.canvas)
        self.frames_scale.set_adjustment(self.data_adjustment)
        self.frames_pop.set_relative_to(self.frames_btn)
        self.frames_pop.set_position(Gtk.PositionType.TOP)

        # signals
        self.frames_pop.connect('closed', self.on_frames_popup_closed)
        self.frames_scale.connect('change-value', self.on_frames_updated)
        self.frames_close_btn.connect('clicked', self.on_frames_popup_closed)
        self.frames_btn.connect('toggled', self.on_frames_toggled)
        self.canvas.connect('image-loaded', self.on_data_loaded)
        self.canvas.connect('motion_notify_event', self.on_mouse_motion)
        self.info_btn.connect('clicked', self.on_image_info)
        self.play_btn.connect('clicked', self.on_play)
        self.reset_btn.connect('clicked', self.on_reset_filters)
        self.open_btn.connect('clicked', self.on_file_open)
        self.save_btn.connect('clicked', self.on_file_save)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.back_btn.connect('clicked', self.on_go_back, False)
        self.zoom_fit_btn.connect('clicked', self.on_go_back, True)
        self.info_close_btn.connect('clicked', self.on_info_hide)
        self.colorize_btn.connect('toggled', self.on_colorize_toggled)
        self.annotate_btn.connect('toggled', self.on_annotate_toggled)

        self.add(self.image_viewer)
        self.show_all()

    @staticmethod
    def open_reflections(filename, hkl=False):
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

    def open_dataset(self, filename):
        self.canvas.open_path(filename)

    def show_frame(self, frame):
        if self.updating:
            self.canvas.show_frame(frame)

    def reset_dataset(self):
        self.frames_pop.popdown()
        self.dataset = self.frame.dataset
        if len(self.dataset.series):
            self.frames_btn.set_sensitive(True)
            self.data_adjustment.set_lower(self.dataset.series[0])
            self.data_adjustment.set_upper(self.dataset.series[-1])
            values = numpy.unique(numpy.linspace(self.dataset.series[0], self.dataset.series[-1], 5).astype(int))
            self.frames_scale.clear_marks()
            for value in values:
                self.frames_scale.add_mark(value, Gtk.PositionType.BOTTOM, f'{value}')
        else:
            self.frames_btn.set_sensitive(False)

        self.frames_scale.set_value(self.frame.index)

    def follow_frames(self):
        self.canvas.load_next()
        if time.time() > self.follow_timeout:
            self.following = False
            status = 'off'
            self.play_btn.set_icon_name(self.icons[status])
        return self.following

    def pause(self):
        self.following = False
        self.updating = False
        self.canvas.pause()
        self.play_btn.set_icon_name(self.icons["off"])

    def on_reset_filters(self, widget):
        self.canvas.reset_filters()
        self.canvas.set_reflections(None)

    def on_go_back(self, widget, full):
        self.canvas.go_back(full)
        return True

    def on_mouse_motion(self, widget, event):
        x, y, resolution, intensity = self.canvas.get_position(event.x, event.y)
        self.info_pos.set_markup(f"<tt><small>X:{x:6}\nY:{y:6}</small></tt>")
        self.info_data.set_markup(f"<tt><small>I:{intensity:6}\nÅ:{resolution:6.2f}</small></tt>")
        self.info_pos.set_alignment(1, 0.5)
        self.info_data.set_alignment(1, 0.5)

    def on_data_loaded(self, obj=None):
        self.frame = self.canvas.get_image_info()

        if self.frame.dataset is not self.dataset:
            self.reset_dataset()

        self.frames_scale.set_value(self.frame.dataset.index)

        directory = self.frame.dataset.directory
        if directory:
            os.chdir(directory)

        self.save_btn.set_sensitive(True)
        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.colorize_btn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.play_btn.set_sensitive(True)
        self.info_btn.set_sensitive(True)
        self.prev_btn.set_sensitive(True)
        self.next_btn.set_sensitive(True)
        self.annotate_btn.set_sensitive(True)

        for name, fmt in list(self.Formats.items()):
            field_name = f'{name}_lbl'
            field = getattr(self, field_name, None)
            value = getattr(self.frame, name, None)
            if value is None:
                value = getattr(self.dataset.frame, name, None)

            if field is not None and value is not None:
                if name in ['size', 'center']:
                    txt = fmt.format(x=value.x, y=value.y)
                else:
                    txt = fmt.format(value)
                field.set_text(txt)
        self.follow_timeout = time.time() + MAX_FOLLOW_DURATION

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
                refl = self.open_reflections(filename, hkl=(file_type == 'XDS ASCII file'))
                self.canvas.set_reflections(refl)
            else:
                self.open_dataset(os.path.abspath(filename))

    def on_file_save(self, widget):
        filename, flt = dialogs.select_save_file("Save display to file")
        if filename:
            path = os.path.abspath(filename)
            self.canvas.save_surface(path)

    def on_colorize_toggled(self, button):
        self.canvas.colorize(self.colorize_btn.get_active())

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
                GLib.timeout_add(100, self.follow_frames)
                self.follow_timeout = time.time() + MAX_FOLLOW_DURATION
            else:
                status = "off"
        self.play_btn.set_icon_name(self.icons[status])

    def on_frames_toggled(self, btn):
        if btn.get_active():
            self.frames_pop.popup()
        else:
            self.frames_pop.popdown()

    def on_annotate_toggled(self, btn):
        self.canvas.set_annotations(btn.get_active())

    def on_frames_popup_closed(self, widget):
        self.frames_btn.set_active(False)
        self.frames_pop.popdown()

    def on_frames_updated(self, scale, scroll, value):
        sequence = self.frame.dataset.series
        frame_number = int(value)
        if frame_number in sequence:
            self.canvas.load_frame(frame_number)


