import os
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
    aln = Gtk.Alignment.new(0.5,0.5,0,0)
    aln.set_padding(0,0,6,6)
    box = Gtk.HBox(False,2)
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
