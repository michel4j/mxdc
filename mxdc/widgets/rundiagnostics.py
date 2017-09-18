'''
Created on Jan 19, 2010

@author: michel
'''

import os
from gi.repository import Gtk
from gi.repository import GObject
from mxdc.widgets.plotter import Plotter
import logging
from mxdc.widgets.textviewer import TextViewer, GUIHandler
from mxdc.utils import gui


(
    DIAGNOSTICS_COLUMN_DISPLAY,
    DIAGNOSTICS_COLUMN_DESCRIPTION,
    DIAGNOSTICS_COLUMN_COLOR,
    DIAGNOSTICS_COLUMN_DATA,
) = range(4)


class DiagnosticsWidget(Gtk.Frame):
    def __init__(self):
        GObject.GObject.__init__(self)
        self.set_shadow_type(Gtk.ShadowType.NONE)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/run_diagnostics'), 
                                  'run_diagnostics')
        self._create_widgets()
        
        for item  in test_data:
            self.add_diagnostic(item)
            
        self.show_all()


    def __getattr__(self, key):
        try:
            return super(DiagnosticsWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        self.add(self.run_diagnostics)
        self.plotter = Plotter()
        self.plotter.set_size_request(400,300)
        self.run_diagnostics.pack_start(self.plotter, True, True, 0)
        
        #logging
        self.log_viewer = TextViewer(self.log_view, font='Sans 7')
        log_handler = GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s: %(message)s', '%d/%m %H:%M')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        self.listmodel = Gtk.ListStore(
            bool,
            str,
            str,
            object)
        self.listview.set_rules_hint(True)

        self.listview.set_model(self.listmodel)
        
        # Display Column
        renderer = Gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_row_toggled, self.listmodel)
        column = Gtk.TreeViewColumn('Display', renderer, active=DIAGNOSTICS_COLUMN_DISPLAY)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_fixed_width(50)
        self.listview.append_column(column)

        # Description Column
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn('Description', renderer, text=DIAGNOSTICS_COLUMN_DESCRIPTION)
        column.set_cell_data_func(renderer, self._set_color)                                  
        self.listview.append_column(column)

    def _set_color(self, column, renderer, model, iter):
        value = model.get_value(iter, DIAGNOSTICS_COLUMN_COLOR)
        renderer.set_property("foreground", value)
        return

    def on_row_toggled(self, cell, path, model):
        iter = model.get_iter(path)
        value = model.get_value(iter, DIAGNOSTICS_COLUMN_DISPLAY)                 
        model.set(iter, DIAGNOSTICS_COLUMN_DISPLAY, (not value) )
        #FIXME: redraw the graph here         
        return True
    
    def add_diagnostic(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter,
            DIAGNOSTICS_COLUMN_DISPLAY, item[DIAGNOSTICS_COLUMN_DISPLAY],
            DIAGNOSTICS_COLUMN_DESCRIPTION, item[DIAGNOSTICS_COLUMN_DESCRIPTION],
            DIAGNOSTICS_COLUMN_COLOR, item[DIAGNOSTICS_COLUMN_COLOR],
            DIAGNOSTICS_COLUMN_DATA, item[DIAGNOSTICS_COLUMN_DATA],
        )
        
test_data = [
    (True, 'Beam X-Position', '#990000', 0),
    (True, 'Beam Y-Position', '#990099', 0),
    (True, 'Image Ice Rings', '#000000', 0),
    (True, 'Average Intensity', '#000099', 0),
    (True, 'RMSD Intensity', '#009999', 0),
    (True, 'Available Disk Space', '#339966', 0),
    (True, 'Ring Current', '#ff9966', 0),
]

if __name__ == '__main__':
       
    win = Gtk.Window()
    win.set_border_width(6)

    diag = DiagnosticsWidget()
    win.add(diag)
    win.show_all()
    win.connect('destroy', lambda x: Gtk.main_quit())
    Gtk.main()

        