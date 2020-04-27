import os

import gi
import numpy

gi.require_version('WebKit2', '4.0')
from gi.repository import GLib, WebKit2
from mxdc import conf
from mxdc.utils import gui


DOCS_PATH = os.path.join(conf.DOCS_DIR, 'index.html')


class Browser(gui.Builder):
    gui_roots = {
        'data/browser': ['browser']
    }

    def __init__(self, parent):
        super().__init__()
        self.view = WebKit2.WebView()
        self.options = {}
        self.setup()
        self.browser.set_transient_for(parent)
        self.browser.show_all()
        self.browser.present()

    def setup(self):
        self.content_box.add(self.view)

        browser_settings = WebKit2.Settings()
        browser_settings.set_property("allow-universal-access-from-file-urls", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.view.set_settings(browser_settings)
        self.browser.set_keep_above(False)

        self.back_btn.connect('clicked', self.go_back)
        self.forward_btn.connect('clicked', self.go_forward)
        self.view.connect('decide-policy', self.check_history)
        self.view.connect('realize', self.on_realized)

    def on_realized(self, *args, **kwargs):
        uri = 'file://{}?v={}'.format(DOCS_PATH, numpy.random.rand())
        GLib.idle_add(self.view.load_uri, uri)

    def go_back(self, btn):
        self.view.go_back()

    def go_forward(self, btn):
        self.view.go_forward()

    def check_history(self, *args, **kwargs):
        self.back_btn.set_sensitive(self.view.can_go_back())
        self.forward_btn.set_sensitive(self.view.can_go_forward())




