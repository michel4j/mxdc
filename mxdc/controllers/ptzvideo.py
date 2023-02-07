import os
from pathlib import Path
from mxdc.devices.interfaces import IPTZCameraController
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget, VideoBox

logger = get_module_logger(__name__)


class AxisController(object):
    def __init__(self, widget, camera):
        self.timeout_id = None
        self.max_fps = 20
        self.camera = camera
        self.widget = widget

        self.setup()

    def save_image(self, filename):
        img = self.camera.get_frame()
        img.save(filename)

    # callbacks
    def on_save(self, obj=None, arg=None):
        filters = {
            'png': dialogs.SmartFilter(name='PNG Image', extension='png'),
            'jpg': dialogs.SmartFilter(name='JPEG Image', extension='jpg')
        }
        img_filename, file_format = dialogs.file_chooser.select_to_save(title='Save Video Snapshot', filters=filters)
        if not img_filename:
            return
        if os.access(Path(img_filename).parent, os.W_OK):
            self.save_image(img_filename)

    def on_zoom_in(self, widget):
        self.camera.zoom(600)
        return True

    def on_zoom_out(self, widget):
        self.camera.zoom(-600)
        return True

    def on_unzoom(self, widget):
        self.camera.zoom(0)
        return True

    def on_image_click(self, widget, event):
        if event.button == 1:
            im_x, im_y = int(event.x / self.video.scale), int(event.y / self.video.scale)
            self.camera.center(im_x, im_y)
        return True

    def on_view_changed(self, widget):
        itr = widget.get_active_iter()
        model = widget.get_model()
        value = model.get_value(itr, 0)
        self.camera.goto(value)

    def setup(self):
        # zoom
        self.widget.hutch_zoomout_btn.connect('clicked', self.on_zoom_out)
        self.widget.hutch_zoomin_btn.connect('clicked', self.on_zoom_in)
        self.widget.hutch_zoom100_btn.connect('clicked', self.on_unzoom)

        # Video Area
        self.video = VideoWidget(self.camera)
        self.widget.hutch_video_frame.add(self.video)

        # presets
        if IPTZCameraController.providedBy(self.camera):
            self.video.connect('button_press_event', self.on_image_click)
            for val in self.camera.get_presets():
                self.widget.hutch_presets_btn.append_text(val)
            self.widget.hutch_presets_btn.connect('changed', self.on_view_changed)

        # status, save, etc
        self.widget.hutch_save_btn.connect('clicked', self.on_save)
