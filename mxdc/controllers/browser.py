import gi

gi.require_version('WebKit2', '4.0')
from gi.repository import WebKit2
from mxdc.utils import gui


class Browser(gui.Builder):
    gui_roots = {
        'data/browser': ['browser']
    }

    def __init__(self, parent=None, title='MxDC Documentation', size=(820, 600), modal=False):
        super().__init__()
        self.view = WebKit2.WebView()
        self.visible = False
        self.options = {}
        self.size = size
        self.title = title
        self.parent = parent
        self.modal = False if parent is None else modal

        self.header.set_title(self.title)
        self.browser.set_keep_above(self.modal)
        if self.modal:
            self.browser.props.modal = self.modal
        self.content_box.set_size_request(*self.size)

        self.setup()

    def setup(self):
        self.content_box.add(self.view)

        browser_settings = WebKit2.Settings()
        browser_settings.set_property("allow-universal-access-from-file-urls", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.view.set_settings(browser_settings)

        self.back_btn.connect('clicked', self.go_back)
        self.forward_btn.connect('clicked', self.go_forward)
        self.view.connect('decide-policy', self.check_history)

        self.view.connect('load-changed', self.on_loading)

    def on_loading(self, view, event):
        if event == WebKit2.LoadEvent.FINISHED and not self.visible:
            self.visible = True
            self.browser.show_all()
            self.browser.present()

    def go_to(self, url):
        self.view.load_uri(url)

    def go_back(self, btn):
        self.view.go_back()

    def go_forward(self, btn):
        self.view.go_forward()

    def check_history(self, *args, **kwargs):
        self.back_btn.set_sensitive(self.view.can_go_back())
        self.forward_btn.set_sensitive(self.view.can_go_forward())

    def destroy(self):
        self.browser.destroy()



