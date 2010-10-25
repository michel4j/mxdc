import gtk, gobject
import gtk.glade
import sys, os
import logging

from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.collectmanager import CollectManager
from mxdc.widgets.scanmanager import ScanManager
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.screeningmanager import ScreenManager
from mxdc.widgets.samplemanager import SampleManager
from bcm.utils.log import get_module_logger, log_to_console
from mxdc.widgets.splash import Splash
from mxdc.widgets.statuspanel import StatusPanel
from bcm.engine.scripting import get_scripts

_logger = get_module_logger('mxdc')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')
COPYRIGHT = """
Copyright (c) 2006-2010, Canadian Light Source, Inc
All rights reserved.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE CANADIAN LIGHT SOURCE BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

class AppWindow(gtk.Window):
    def __init__(self, version='3.3.4'):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self._xml = gtk.glade.XML(os.path.join(SHARE_DIR, 'mxdc_main.glade'), 'mxdc_main')
        self.set_position(gtk.WIN_POS_CENTER)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self.set_icon_from_file(self.icon_file)
        self.set_title('MxDC - Mx Data Collector')
        self.version = version
        self.splash = Splash(version)
        self.splash.set_transient_for(self)
        self.splash.show_all()
        while gtk.events_pending():
            gtk.main_iteration()

    def __getattr__(self, key):
        try:
            return super(AppWindow).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def run(self):
        gobject.timeout_add(2000, lambda: self.splash.hide())         
        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)       
        self.hutch_manager = HutchManager()
        self.sample_manager = SampleManager()
        self.sample_manager.connect('samples-changed', self.on_samples_changed)
        self.screen_manager = ScreenManager()
        self.status_panel = StatusPanel()
        
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )
        
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('  Beamline Setup  '))
        notebook.append_page(self.sample_manager, tab_label=gtk.Label('  Samples  '))
        notebook.append_page(self.screen_manager, tab_label=gtk.Label('  Screening  '))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('  Data Collection '))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('  Fluorescence Scans  '))
        #self.screen_manager.set_sensitive(False)
        notebook.set_border_width(6)

        self.main_frame.add(notebook)
        self.mxdc_main.pack_start(self.status_panel, expand = False, fill = False)
        #self.status_bar.pack_end(gtk.Label('Beamline'))
        self.add(self.mxdc_main)
        self.scripts = get_scripts()
        self.mounting_mnu.connect('activate', self.hutch_manager.on_mounting)
        self.centering_mnu.connect('activate', self.hutch_manager.on_centering)
        self.collect_mnu.connect('activate', self.hutch_manager.on_collection)

        self.show_all()
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            ]
        about = gtk.AboutDialog()
        about.set_name("MX Data Collector")
        about.set_version(self.version)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        about.set_program_name('MxDC')
        logo = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        about.set_logo(logo)
        
        about.connect('response', lambda x,y: about.destroy())
        about.connect('destroy', lambda x: about.destroy())
        about.set_transient_for(self)
        about.show()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        
    def on_samples_changed(self, obj, ctx):
        samples = ctx.get_loaded_samples()
        self.screen_manager.add_samples(samples)
