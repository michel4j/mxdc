from gi.repository import GObject
from gi.repository import Gtk, Gdk
from mxdc.utils import scitools, colors, gui


def hex2rgba(spec, alpha=0.5):
    col = Gdk.RGBA()
    col.parse(spec)
    col.alpha = alpha
    return col


TYPE_COLORS = list(map(hex2rgba, colors.Category.CAT20))
EDGE_COLORS = list(map(hex2rgba, colors.Category.EDGES))


def set_area_cursor(widget, cursor='pointer'):
    widget.get_window().set_cursor(
        Gdk.Cursor.new_from_name(Gdk.Display.get_default(), cursor)
    )
    return True


class EdgeMenu(gui.BuilderMixin):
    gui_roots = {
        'data/edge_menu': ['edge_menu']
    }

    def __init__(self):
        self.setup_gui()
        self.build_gui()
        self.entry = None
        self.element = None
        for edge in ['K', 'L1', 'L2', 'L3']:
            ebox = getattr(self, 'edge_{}'.format(edge), None)
            ebox.connect('realize', set_area_cursor, 'pointer')
            ebox.connect('button-release-event', self.edge_selected, edge)

    def set_entry(self, entry):
        self.entry = entry

    def edge_selected(self, widget, event, edge):
        self.entry.set_text('') # make sure 'changed' signal fires at least once
        self.entry.set_text('{}-{}'.format(self.element['symbol'], edge))

    def configure(self, element, edges):
        self.edge_menu.set_sensitive(True)
        self.element = element
        self.elem_z_lbl.set_text(str(element['Z']))
        self.elem_sym_lbl.set_text(element['symbol'])
        self.elem_name_lbl.set_text(element['name'])
        self.elem_mass_lbl.set_text('{:0.2f}'.format(element['mass']))
        for edge in ['K', 'L1', 'L2', 'L3']:
            elem_edge = "{}-{}".format(element['symbol'], edge)
            ebox = getattr(self, 'edge_{}'.format(edge), None)
            if elem_edge in edges:
                ebox.set_sensitive(True)
                ebox.get_style_context().remove_class('disabled')
            else:
                ebox.set_sensitive(False)
                ebox.get_style_context().add_class('disabled')


class EdgeSelector(Gtk.Grid):
    __gsignals__ = {
        'edge': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'element': (GObject.SignalFlags.RUN_FIRST, None, (str,))
    }

    def __init__(self, min_energy=2.0, max_energy=20.0, xrf_offset=1.5):
        super(EdgeSelector, self).__init__(column_spacing=1, row_spacing=1)
        self.set_column_homogeneous(True)
        self.set_row_homogeneous(False)
        self.min_energy = min_energy
        self.max_energy = max_energy
        self.xrf_offset = xrf_offset
        self.menu = EdgeMenu()
        self.attach(self.menu.edge_menu, 2, 1, 10, 3)
        # self.close_btn = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.BUTTON)
        # self.close_btn.set_tooltip_text('Close Periodic Table')
        # self.close_btn.set_relief(Gtk.ReliefStyle.NONE)
        # self.attach(self.close_btn, 15, 1, 2, 1)
        self.entry = None
        self.emissions = scitools.get_energy_database(min_energy, max_energy)
        for symbol in list(scitools.PERIODIC_TABLE.keys()):
            element, edges = self.get_element(symbol)
            elm_box = Gtk.EventBox()
            elm_box.override_background_color(Gtk.StateType.NORMAL, TYPE_COLORS[int(element['type'])])
            label = Gtk.Label(label=element['symbol'], margin=1)
            label.set_padding(2, 6)
            elm_box.add(label)
            style = elm_box.get_style_context()
            style.add_class('element-box')

            if element['period'] in [8,9] and element['group'] == 4:
                style.add_class('la-ac-gap-left')
            elif element['group'] == 3 and element['period'] in [6,7]:
                style.add_class('la-ac-gap-right')
            if edges:
                elm_box.connect('button-release-event', self.select_element, element['symbol'])
                elm_box.set_sensitive(True)
                elm_box.connect('realize', set_area_cursor, 'pointer')
            else:
                elm_box.set_sensitive(False)

            self.attach(elm_box, element['group'] - 1, element['period'], 1, 1)
        self.show_all()

    def set_entry(self, entry):
        self.menu.set_entry(entry)

    def get_element(self, symbol):
        edge_list = [
            "{}-{}".format(symbol, edge)
            for edge in ['K', 'L1', 'L2', 'L3']
            if "{}-{}".format(symbol, edge) in self.emissions
        ]
        element = scitools.PERIODIC_TABLE[symbol]
        return element, edge_list

    def get_edge_specs(self, edge):
        return self.emissions[edge]

    def get_excitation_for(self, edge):
        if not edge:
            return self.max_energy
        else:
            absorption, emission = self.emissions[edge]
            return min(absorption + self.xrf_offset, self.max_energy)  # 1.5 keV above desired edge

    def select_element(self, widget, event, symbol):
        if event.button == 1:
            element, edges = self.get_element(symbol)
            self.menu.configure(element, edges)

