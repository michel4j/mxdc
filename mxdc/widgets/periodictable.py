from gi.repository import Gtk, Gdk
from gi.repository import GObject
from mxdc.utils import science


class PeriodicTable(Gtk.Alignment):
    __gsignals__ = {
        'edge-selected': (GObject.SignalFlags.RUN_FIRST, None,
                      (GObject.TYPE_STRING,))
    }

    def __init__(self, loE=4, hiE=18):
        super(PeriodicTable, self).__init__()
        
        # set parameters
        self.low_energy = loE
        self.high_energy = hiE
        self.edge = 'Se-K'
        self.energy = 12.658
        self.type_colors = ["#ff9999","#ff99ff","#9999ff","#cc99ff",
                            "#99ccff","#99ffff","#99ff99","#ccff99",
                            "#ffcc99","#ff6666", "#cccccc", "#ffff99"]
        self.edge_colors = ["#de7878","#de78de","#7878de","#ab78de",
                            "#7899de","#78dede","#78de78","#abde78",
                            "#deab78","#de4545", "#ababab", "#dede78"]

        self.table = Gtk.Table(4,18,True)
        science.PERIODIC_TABLE = science.PERIODIC_TABLE
                    
        # set the title
        self.title = Gtk.Label(label='<big><big><b>Select an X-ray Absorption Edge</b></big></big>')
        self.title.set_use_markup(True)
        self.table.attach(self.title,3,14,0,1)
                
        # populate table and display it
        self._populate_table()
        self.table.set_row_spacings(1)
        self.table.set_col_spacings(1)
        self.table.set_row_spacing(6,2)
        self.add(self.table)
        self.show_all()

    def _populate_table(self):
        # parse data file and populate table
        edge_names = ['K','L1','L2','L3']
        # Verify L1 emission lines
        emissions = science.get_energy_database()
        
        for key in science.PERIODIC_TABLE.keys():
            element_container = Gtk.VBox(False, 0)
            element_container.set_border_width(0)

            # Atomic number
            label1 = Gtk.Label(label="<small><span color='slategray'><tt>%s</tt></span></small>" % (science.PERIODIC_TABLE[key]['Z']))
            label1.set_use_markup(True)
            label1.set_alignment(0.1,0.5)
            element_container.pack_start(label1, True, True, 0)
            
            # Element Symbol
            label2 = Gtk.Label(label="<big>%s</big>" % (key) )
            label2.set_use_markup(True)
            element_container.pack_start(label2,True, True,0)

            # Edges
            edge_container = Gtk.HBox(True,0)
            edge_container.set_spacing(1)           
            el_type = int( science.PERIODIC_TABLE[key]['type'] )
            el_name = science.PERIODIC_TABLE[key]['name']
            for edge in edge_names:
                edge_descr = "%s-%s" % (key, edge)
                val, e_val = emissions.get(edge_descr, (0.0, 0.0))
                if val > self.low_energy and val < self.high_energy and e_val < self.high_energy:
                    event_data = "%s:%s:%s" % (edge_descr,val,e_val)
                    edge_label = Gtk.Label(label="<small><b><sub><span color='blue'>%s</span></sub></b></small>" % (edge) )
                    edge_label.set_padding(1,1)
                    edge_label.set_use_markup(True)
                    edge_bgbox = Gtk.EventBox()
                    edge_bgbox.add(edge_label)
                    #edge_bgbox.modify_bg(Gtk.StateType.NORMAL, edge_bgbox.get_colormap().alloc_color( self.edge_colors[el_type] ))
                    edge_bgbox.connect('button_press_event',self.select_edge,event_data)
                    edge_bgbox.connect('realize',self.set_area_cursor)
                    edge_container.pack_start(edge_bgbox, True, True, 0)
                    edge_bgbox.set_tooltip_markup("Edge: %s (%s)<br/>Absorption: %g keV<br/>Emission: %g keV" % (el_name, edge_descr, val,e_val) )

            
            element_container.pack_start(edge_container,True, True,0)

            # determine where to place in table from Group and Period fields
            ra = int(science.PERIODIC_TABLE[key]['group']) # Group
            la = ra -1
            ba = int(science.PERIODIC_TABLE[key]['period']) # period
            ta = ba -1
            element_bgbox = Gtk.EventBox() 
            element_bgbox.add(element_container)
            color = self.type_colors[ el_type ]
            #element_bgbox.modify_bg(Gtk.StateType.NORMAL, element_bgbox.get_colormap().alloc_color( color ))
            element_bgbox.show()          
            self.table.attach(element_bgbox,la,ra,ta,ba)

    def select_edge(self,widget,event,data):
        vals = data.split(':')
        self.edge = vals[0]
        self.energy = float(vals[1])
        self.emission = float(vals[2])
        #self.edge_label.set_text("Edge: %11s" % vals[0])
        #self.energy_label.set_text("Energy: %8s keV" % vals[1])
        self.emit('edge-selected', data)
        return True

    def set_area_cursor(self,widget):
        widget.get_window().set_cursor(Gdk.Cursor.new(Gdk.HAND2))
        return True

