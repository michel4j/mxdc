import gtk, gobject
import bcm.utils

class PeriodicTable(gtk.Alignment):
    __gsignals__ = {
        'edge-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,))
    }

    def __init__(self, loE=4, hiE=18):
        self.__gobject_init__() 
        gtk.Alignment.__init__(self,0.5,0.5,0,0)
        
        # set parameters
        self.low_energy = loE
        self.high_energy = hiE
        self.edge = 'Se-K'
        self.energy = 12.658
        self.type_colors = ["#ff9999","#ff99ff","#9999ff","#cc99ff","#99ccff","#99ffff","#99ff99","#ccff99","#ffcc99","#ff6666", "#cccccc", "#ffff99"]
        self.edge_colors = ["#de7878","#de78de","#7878de","#ab78de","#7899de","#78dede","#78de78","#abde78","#deab78","#de4545", "#ababab", "#dede78"]

        self.table = gtk.Table(4,18,True)
        self.table_data = bcm.utils.read_periodic_table()
                    
        # set the title
        self.title = gtk.Label('<big><big><b>Select an X-ray Absorption Edge</b></big></big>')
        self.title.set_use_markup(True)
        self.table.attach(self.title,3,14,0,1)
                
        # populate table and display it
        self.populate_table()
        self.table.set_row_spacings(1)
        self.table.set_col_spacings(1)
        self.table.set_row_spacing(6,4)
        self.add(self.table)
        self.show_all()

    def populate_table(self):
        # parse data file and populate table
        self.tooltips = gtk.Tooltips()
        edge_names = ['K','L1','L2','L3']
        # Verify L1 emission lines
        emissions = {
            'K':  'Ka',
            'L1': 'Lg2',
            'L2': 'Lb2',
            'L3': 'Lb1'
        } 
        for key in self.table_data.keys():
            element_container = gtk.VBox(False, 0)
            element_container.set_border_width(0)

            # Atomic number
            label1 = gtk.Label("<small><span color='slategray'><tt>%s</tt></span></small>" % (self.table_data[key]['No.']) )
            label1.set_use_markup(True)
            label1.set_alignment(0.1,0.5)
            element_container.pack_start(label1)
            
            # Element Symbol
            label2 = gtk.Label("<big>%s</big>" % (key) )
            label2.set_use_markup(True)
            element_container.pack_start(label2,padding=1)

            # Edges
            edge_container = gtk.HBox(True,0)
            edge_container.set_spacing(1)           
            el_type = int( self.table_data[key]['Type'] )
            for edge in edge_names:
                name = edge
                val = float(self.table_data[key][edge])
                e_val = float(self.table_data[key][ emissions[edge] ])
                if val > self.low_energy and val < self.high_energy and e_val < self.high_energy:
                    event_data = "%s-%s:%s:%s" % (key,name,val,e_val)
                    edge_label = gtk.Label("<small><b><sub><span color='blue'>%s</span></sub></b></small>" % (name) )
                    edge_label.set_padding(2,2)
                    edge_label.set_use_markup(True)
                    edge_bgbox = gtk.EventBox()
                    edge_bgbox.add(edge_label)
                    edge_bgbox.modify_bg(gtk.STATE_NORMAL, edge_bgbox.get_colormap().alloc_color( self.edge_colors[el_type] ))
                    edge_bgbox.connect('button_press_event',self.select_edge,event_data)
                    edge_bgbox.connect('realize',self.set_area_cursor)
                    edge_container.pack_start(edge_bgbox)
                    self.tooltips.set_tip(edge_bgbox, "Edge: %s-%s\nAbsorption: %g keV\nEmission: %g keV" % (key, name, val,e_val) )

            
            element_container.pack_start(edge_container,padding=1)

            # determine where to place in table from Group and Period fields
            ra = int(self.table_data[key]['Group']) # Group
            la = ra -1
            ba = int(self.table_data[key]['Period']) # period
            ta = ba -1
            element_bgbox = gtk.EventBox() 
            element_bgbox.add(element_container)
            color = self.type_colors[ el_type ]
            element_bgbox.modify_bg(gtk.STATE_NORMAL, element_bgbox.get_colormap().alloc_color( color ))
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
        widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
        return True

gobject.type_register(PeriodicTable)
