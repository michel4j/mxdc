import os
import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk


class GUIFile(object):
    def __init__(self, name, root=None):
        self.name = name
        self.root = root
        self.wTree = Gtk.Builder()
        self.ui_file = "%s.ui" % self.name
        if os.path.exists(self.ui_file):
            if self.root is not None:
                self.wTree.add_objects_from_file(self.ui_file, [self.root])
            else:
                self.wTree.add_from_file(self.ui_file)

    def get_widget(self, name):
        return self.wTree.get_object(name)


def make_icon_label(txt, stock_id=None):
    aln = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1, yscale=1)
    aln.set_padding(0, 0, 6, 6)
    box = Gtk.Box(False, 2, orientation=Gtk.Orientation.HORIZONTAL)
    aln.label = Gtk.Label(label=txt)
    aln.label.set_use_markup(True)
    box.pack_end(aln.label, False, False, 0)
    aln.icon = Gtk.Image()
    box.pack_start(aln.icon, False, False, 0)
    if stock_id is not None:
        aln.icon.set_from_stock(stock_id, Gtk.IconSize.MENU)
    aln.add(box)
    aln.show_all()
    return aln


def make_tab_label(txt):
    label = Gtk.Label(label=txt)
    label.set_padding(6, 0)
    return label


class BuilderMixin(object):
    gui_top = os.path.join(os.environ['MXDC_PATH'], 'mxdc', 'widgets')
    gui_roots = {
        'relative/path/to/file_without_extension': ['root_object']
    }

    def setup_gui(self):
        self.gui_objects = {
            root: GUIFile(os.path.join(self.gui_top, path), root)
            for path, roots in self.gui_roots.items() for root in roots
            }

    def build_gui(self):
        pass

    def __getattr__(self, item):
        if self.gui_objects:
            for xml in self.gui_objects.values():
                obj = xml.get_widget(item)
                if obj:
                    return obj
        raise AttributeError
