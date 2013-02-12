from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.misc import ActiveLabel, StatusBox
from twisted.python.components import globalRegistry
import gtk

class StatusPanel(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)
        self.layout_table = gtk.Table(1, 9, True)
        self.layout_table.set_col_spacings(2)
        self.layout_table.set_border_width(2)

        beamline = globalRegistry.lookup([], IBeamline)
        if beamline is None:
            return
        
        options = {
            'xoptions' : gtk.EXPAND|gtk.FILL,
            }
        self.layout_table.attach(self._frame_control('Beamline', gtk.Label(beamline.name), gtk.SHADOW_IN), 8, 9 , 0, 1, **options)
        
        beamline.ring_current.units = 'mA'
        self.cur = ActiveLabel(beamline.ring_current, fmt="%+0.1f")
        self.layout_table.attach(self._frame_control('Ring', self.cur, gtk.SHADOW_IN), 7, 8 , 0, 1, **options)
        
        self.i2 = ActiveLabel(beamline.i_2.value, fmt="%+0.2e")
        self.layout_table.attach(self._frame_control('I2', self.i2, gtk.SHADOW_IN), 6, 7 , 0, 1, **options)
        
        self.i1 = ActiveLabel(beamline.i_1.value, fmt="%+0.2e")
        self.layout_table.attach(self._frame_control('I1', self.i1, gtk.SHADOW_IN), 5, 6 , 0, 1, **options)
        
        self.i0 = ActiveLabel(beamline.i_0.value, fmt="%+0.2e")
        self.layout_table.attach(self._frame_control('I0', self.i0, gtk.SHADOW_IN), 4, 5 , 0, 1, **options)
        
        _cmap = {True:'green',  False:'red'}
        _vmap = {True:'OPEN',  False:'CLOSED'}
        self.sh_stat = StatusBox(beamline.registry['exposure_shutter'], color_map=_cmap, value_map=_vmap)
        self.layout_table.attach(self._frame_control('Shutter', self.sh_stat, gtk.SHADOW_IN), 3, 4 , 0, 1, **options)
      

        _cmap = {'MOUNTING':'blue',
            'CENTERING':'orange',
            'SCANNING':'green',
            'COLLECT': 'green',
            'BEAM': 'red',
            'MOVING': 'gray',
            'INIT':'gray',
            'ALIGN': 'gray',
            }

        self.gonio_mode = StatusBox(beamline.goniometer, signal='mode', color_map=_cmap)
        self.layout_table.attach(self._frame_control('Mode', self.gonio_mode, gtk.SHADOW_IN), 2, 3 , 0, 1, **options)
        
        vseparator = gtk.HSeparator()
        vseparator.set_size_request(-1,3)
        self.pack_start(vseparator, False, True, 2)        
        self.pack_end(self.layout_table, True, True, 0)
        self.show_all()    
    
    def _update_mode(self, obj, val):
        self.gonio_mode.set_markup(val)
        
    def _frame_control(self, label, widget, shadow):
        hbox = gtk.HBox(False, 3)
        hbox.pack_end(widget, expand=True, fill=True)
        if label is not None:
            descr = gtk.Label('<span color="#666666"><b>%s:</b></span>' % label)
            descr.set_use_markup(True)
            hbox.pack_start(gtk.VSeparator(), expand=False, fill=True)
            hbox.pack_start(descr, expand=False, fill=True)

        return hbox
            
