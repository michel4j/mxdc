
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GdkPixbuf
from mxdc.beamline.mx import MXBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.interface.beamlines import IBeamline
from mxdc.utils import gui
from mxdc.utils.log import get_module_logger, log_to_console
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.minihutchman import MiniHutchManager
from mxdc.widgets.samplepicker import SamplePicker
from twisted.python.components import globalRegistry
import os

logger = get_module_logger(__name__)
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')
COPYRIGHT = "Copyright (c) 2006-2010, Canadian Light Source, Inc. All rights reserved."


class HutchWindow(Gtk.ApplicationWindow):
    def __init__(self):
        super(HutchWindow, self).__init__(Gtk.WindowType.TOPLEVEL)
        self._xml = gui.GUIFile(os.path.join(SHARE_DIR, 'mxdc_main'), 'mxdc_main')
        self.set_position(Gtk.WindowPosition.CENTER)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self.set_title('Hutch Viewer')

    def __getattr__(self, key):
        try:
            return super(HutchWindow, self).__getattr__(key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def run(self):
        icon = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        self.set_icon(icon)
        self.set_resizable(False)

        self.hutch_manager = MiniHutchManager()
        
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )            

        self.sample_picker = SamplePicker()
        _lbl = Gtk.Label(label='Automounter')
        _lbl.set_padding(6, 0)
        self.hutch_manager.video_book.append_page(self.sample_picker, tab_label=_lbl)
        self.sample_picker.set_border_width(9)

        self.beamline = globalRegistry.lookup([], IBeamline)
        if set(os.getgroups()) & set(self.beamline.config['admin_groups']):
            self.image_viewer = ImageViewer(size=256)
            _lbl = Gtk.Label(label='Diffraction Viewer')
            _lbl.set_padding(6,0)
            self.hutch_manager.device_book.append_page(self.image_viewer, tab_label=_lbl)
            self.beamline.detector._header['filename'].connect('changed', self.on_new_image)
            self.hutch_manager.device_book.set_show_border(False)
        else:
            self.hutch_manager.device_book.set_show_tabs(False)
            self.hutch_manager.device_book.set_show_border(False)

        self.main_frame.add(self.hutch_manager)
        self.mxdc_main.pack_start(self.status_panel, False, False, 0)
        self.add(self.mxdc_main)
        self.scripts = get_scripts()
        # register menu events
        self.mounting_mnu.connect('activate', self.hutch_manager.on_mounting)
        self.centering_mnu.connect('activate', self.hutch_manager.on_centering)
        self.collect_mnu.connect('activate', self.hutch_manager.on_collection)
        self.beam_mnu.connect('activate', self.hutch_manager.on_beam_mode)
        self.open_shutter_mnu.connect('activate', self.hutch_manager.on_open_shutter)
        self.close_shutter_mnu.connect('activate', self.hutch_manager.on_close_shutter)        
        self.show_all()

    def on_new_image(self, widget, index):
        header = self.beamline.detector._header
        filename = '%s/%s' % (header['directory'].get().replace('/data/','/users/'), header['filename'].get())
        self.image_viewer.image_canvas.queue_frame(filename)
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            "Kathryn Janzen",
            ]
        about = Gtk.AboutDialog()
        name = 'Hutch Viewer'
        try:
            about.set_program_name(name)
        except:
            about.set_name(name)
        about.set_version(self.version)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        logo = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        about.set_logo(logo)
        
        about.connect('response', lambda x,y: about.destroy())
        about.connect('destroy', lambda x: about.destroy())
        about.show()


class HutchApp(object):
    def run_local(self):
        MXBeamline()
        self.main_window = HutchWindow()
        self.main_window.connect('destroy', self._do_quit)
        self.main_window.run()        
        
    def _do_quit(self, obj=None):
        logger.info('Stopping...')
        Gtk.main_quit()

def main():
    try:
        _ = os.environ['MXDC_CONFIG']
        logger.info('Starting HutchViewer (%s)... ' % os.environ['MXDC_CONFIG'])
    except:
        logger.error('Could not find Beamline Control Module environment variables.')
        logger.error('Please make sure the BCM is properly installed and configured.')
        Gtk.main_quit()        
    app = HutchApp()
    app.run_local()
        

if __name__ == '__main__':
    log_to_console()
    try:
        GObject.idle_add(main)
        Gtk.main()
    finally:
        logger.info('Stopping...')

