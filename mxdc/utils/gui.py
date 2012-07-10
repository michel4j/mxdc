import os
import gtk

USE_GLADE = True
if gtk.gtk_version < 2.14:
    USE_GLADE = True

if USE_GLADE:
    import gtk.glade

class GUIFile(object):
    def __init__(self, name, root):
        self.name = name
        self.root = root
        self.use_glade = USE_GLADE
        if not self.use_glade:
            self.wTree = gtk.Builder()
            self.ui_file = "%s.ui" % self.name
            if os.path.exists(self.ui_file):
                self.wTree.add_objects_from_file(self.ui_file, [self.root])
                #self.wTree.add_from_file(self.ui_file)
            else:
                self.use_glade = True

        if self.use_glade:
            self.ui_file = "%s.glade" % self.name
            self.wTree = gtk.glade.XML(self.ui_file, self.root)
    
    def get_widget(self, name):
        if self.use_glade:
            return self.wTree.get_widget(name)
        else:
            return self.wTree.get_object(name)