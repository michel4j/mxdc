import os
import sys

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio
from mxdc import conf
from mxdc.utils.log import get_module_logger
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets import dialogs

logger = get_module_logger(__name__)


class ImageApp(object):
    def __init__(self):
        self.win = Gtk.Window()
        self.resources = Gio.Resource.load(os.path.join(conf.SHARE_DIR, 'mxdc.gresource'))
        Gio.resources_register(self.resources)
        dialogs.MAIN_WINDOW = self.win
        self.win.connect("destroy", lambda x: Gtk.main_quit())
        self.win.set_title("Diffraction Image Viewer")
        self.viewer = ImageViewer(int(Gdk.Screen.height() * 0.75))
        self.win.add(self.viewer)
        self.win.show_all()

    def run(self):
        try:
            if len(sys.argv) >= 2:
                self.viewer.open_image(os.path.abspath(sys.argv[1]))
            Gtk.main()
        finally:
            logger.info('Stopping...')
