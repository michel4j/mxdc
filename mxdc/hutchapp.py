import warnings
warnings.simplefilter("ignore")
import sys, os

from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

import gtk
import gobject

from bcm.beamline.mx import MXBeamline
from bcm.utils.log import get_module_logger, log_to_console
from mxdc.widgets.hutchmanager import HutchManager
from bcm.engine.scripting import get_scripts
from mxdc.widgets.statuspanel import StatusPanel
from mxdc.widgets.samplepicker import SamplePicker
from mxdc.utils import gui

#from mxdc.utils import gtkexcepthook

_logger = get_module_logger('hutchviewer')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')
COPYRIGHT = """
Copyright (c) 2006-2010, Canadian Light Source, Inc
All rights reserved.
"""

class HutchWindow(gtk.Window):
    def __init__(self):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self._xml = gui.GUIFile(os.path.join(SHARE_DIR, 'mxdc_main'), 'mxdc_main')
        self.set_position(gtk.WIN_POS_CENTER)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self.set_title('Hutch Viewer')

    def __getattr__(self, key):
        try:
            return super(HutchWindow).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def run(self):
        icon = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        self.set_icon(icon)
        self.set_resizable(False)

        self.hutch_manager = HutchManager()
        self.status_panel = StatusPanel()
        
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )            

        self.sample_picker = SamplePicker()
        _lbl = gtk.Label('Automounter')
        _lbl.set_padding(6, 0)
        self.hutch_manager.video_book.append_page(self.sample_picker, tab_label=_lbl)

        self.main_frame.add(self.hutch_manager)
        self.mxdc_main.pack_start(self.status_panel, expand = False, fill = False)
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
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            "Kathryn Janzen",
            "Kevin Anderson",
            ]
        about = gtk.AboutDialog()
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
        logo = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        about.set_logo(logo)
        
        about.connect('response', lambda x,y: about.destroy())
        about.connect('destroy', lambda x: about.destroy())
        about.set_transient_for(self)
        about.show()


class HutchApp(object):
    def run_local(self):
        _ = MXBeamline()
        self.main_window = HutchWindow()
        self.main_window.connect('destroy', self._do_quit)
        self.main_window.run()        
        
    def _do_quit(self, obj=None):
        _logger.info('Stopping...')
        reactor.stop()

def main():
    try:
        _ = os.environ['BCM_CONFIG_PATH']
        _logger.info('Starting HutchViewer (%s)... ' % os.environ['BCM_BEAMLINE'])
    except:
        _logger.error('Could not find Beamline Control Module environment variables.')
        _logger.error('Please make sure the BCM is properly installed and configured.')
        reactor.stop()
        
    app = HutchApp()
    app.run_local()
        
def main2():
    win = gtk.Window()
    win.connect("destroy", lambda x: reactor.stop())
    win.set_border_width(3)
    win.set_size_request(1167,815)
    
    win.set_title("HutchViewer")
 
    try:
        _ = os.environ['BCM_CONFIG_PATH']
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    bl = MXBeamline()
    
    myviewer = HutchManager()
    myviewer.video_book.connect('realize', lambda x: myviewer.video_book.set_page(1))
    myviewer.tool_book.connect('realize', lambda x: myviewer.tool_book.set_page(1))
    myviewer.show_all()

    win.add(myviewer)
    win.show_all()


if __name__ == '__main__':
    log_to_console()
    try:
        reactor.callWhenRunning(main)
        reactor.run()
    finally:
        _logger.info('Stopping...')

