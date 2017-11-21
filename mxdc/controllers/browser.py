import os
import gi
import numpy

gi.require_version('WebKit', '3.0')
from gi.repository import GObject, WebKit, Gtk, Gdk
from mxdc import conf
from mxdc.conf import settings
from mxdc.utils import gui


DOCS_PATH = os.path.join(conf.DOCS_DIR, 'index.html')


class Browser(gui.Builder):
    gui_roots = {
        'data/browser': ['browser']
    }
    def __init__(self, parent):
        super(Browser, self).__init__()
        self.view = WebKit.WebView()
        self.options = {}
        self.setup()
        self.browser.set_transient_for(parent)
        self.browser.show_all()
        self.browser.present()

    def setup(self):
        self.content_box.add(self.view)

        browser_settings = WebKit.WebSettings()
        browser_settings.set_property("enable-file-access-from-file-uris", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.view.set_settings(browser_settings)

        if settings.show_release_notes():
            self.gotit_btn.set_sensitive(True)
            self.gotit_btn.show()
        else:
            self.browser.set_decorated(True)
            self.browser.set_type_hint(Gdk.WindowTypeHint.NORMAL)
            self.browser.set_keep_above(False)
        self.gotit_btn.connect('clicked', self.close_window, True)
        self.close_btn.connect('clicked', self.close_window, False)
        self.back_btn.connect('clicked', self.go_back)
        self.forward_btn.connect('clicked', self.go_forward)
        self.view.connect('navigation-policy-decision-requested', self.check_history)
        self.view.connect('realize', self.on_realized)

    def on_realized(self, *args, **kwargs):
        uri = 'file://{}?v={}'.format(DOCS_PATH, numpy.random.rand())
        GObject.idle_add(self.view.load_uri, uri)

    def close_window(self, button, disable=False):
        self.browser.destroy()
        if disable:
            settings.disable_release_notes()

    def go_back(self, btn):
        self.view.go_back()

    def go_forward(self, btn):
        self.view.go_forward()

    def check_history(self, *args, **kwargs):
        self.back_btn.set_sensitive(self.view.can_go_back())
        self.forward_btn.set_sensitive(self.view.can_go_forward())




