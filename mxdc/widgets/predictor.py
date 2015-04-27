"""
A Resolution Predictor widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
from gi.repository import Gtk
from gi.repository import GObject
import threading
from gi.repository import Gdk
from gi.repository import Pango
import numpy

from matplotlib.figure import Figure
import matplotlib.cm as cm
from matplotlib.colors import LogNorm
from matplotlib.ticker import NullLocator
from matplotlib import rcParams
from mxdc.utils import converter
from mxdc.utils.log import get_module_logger
import time

_logger = get_module_logger(__name__)

from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
            
class Predictor( Gtk.AspectFrame ):
    def __init__( self, pixel_size=0.07234, detector_size=4096):
        GObject.GObject.__init__(self, obey_child=True, ratio=1.0)
        self.fig = Figure(facecolor='w')
        self.axis = self.fig.add_axes([0.0,0.0,1,1], aspect='equal', frameon=False)
        _fd = self.get_pango_context().get_font_description()
        rcParams['font.family'] = 'sans-serif'
        rcParams['font.sans-serif'] = _fd.get_family()
        rcParams['font.size'] = _fd.get_size()/Pango.SCALE
        self._destroyed = False
        
        self.canvas = FigureCanvas( self.fig )  # a Gtk.DrawingArea
        self.add( self.canvas )
        self.set_shadow_type(Gtk.ShadowType.ETCHED_OUT)
        self.show_all()
        self.pixel_size = pixel_size
        self.detector_size = detector_size
        self.beam_x, self.beam_y = self.detector_size /2, self.detector_size /2
        self.two_theta = 0
        self.wavelength = 1.000
        self.distance = 250.0
        self.last_updated = 0
        self._can_update = True
        self.canvas.set_events(Gdk.EventMask.EXPOSURE_MASK |
                Gdk.EventMask.LEAVE_NOTIFY_MASK |
                Gdk.EventMask.BUTTON_PRESS_MASK |
                Gdk.EventMask.POINTER_MOTION_MASK |
                Gdk.EventMask.POINTER_MOTION_HINT_MASK|
                Gdk.EventMask.VISIBILITY_NOTIFY_MASK)  
        
        self.canvas.connect('visibility-notify-event', self.on_visibility_notify)
        self.canvas.connect('unrealize', self.on_destroy)
        self.connect('unrealize', self.on_destroy)
        
        self.canvas.connect('unmap', self.on_unmap)
        self.canvas.connect_after('map', self.on_map)
        self._do_update = False

        self.calculator = threading.Thread(target=self._do_calc)
        self.calculator.setDaemon(True)
        self.calculator.start()

    def on_destroy(self, obj):
        self._destroyed = True
        
    def display(self, widget=None):
        self.axis.clear()
        self.axis.set_axis_off()
        self.axis.xaxis.set_major_locator(NullLocator())
        self.axis.yaxis.set_major_locator(NullLocator())
        normFunction = LogNorm(vmin=0.4, vmax=50) #Normalize(0, 30)
        self.lines = self._shells(num=int(12*self.Z.min()))
        try:
            cntr = self.axis.contour(self.xp, self.yp, self.Z, self.lines, linewidths=0.75, cmap=cm.gist_heat_r, norm=normFunction)
            self.axis.clabel(cntr, inline=True, fmt='%0.1f',fontsize=8.5)             
            self.canvas.draw()
            self.last_updated = time.time()
        except ValueError:
            _logger.debug('Predictor Widget not updating...')
        return False
        
    def configure(self, **kwargs):
        redraw_pending = False
        for k, v in kwargs.items():
            if k == 'wavelength':
                if (abs(v-self.wavelength) > 0.1): 
                    redraw_pending = True
                    self.wavelength = v
            elif k == 'energy':
                v_ = converter.energy_to_wavelength(abs(v))
                if (abs(v_-self.wavelength) >= 0.1): 
                    redraw_pending = True
                    self.wavelength = v_
            elif k == 'distance':
                if (abs(v-self.distance) >= 1.0): 
                    redraw_pending = True
                    self.distance = abs(v)
            elif k == 'two_theta':
                v_ = v * numpy.pi/ 180.0
                if (abs(v_-self.two_theta) >= 0.05):
                    redraw_pending = True
                    self.two_theta = abs(v_)
            elif k == 'pixel_size':
                if (v != self.pixel_size): 
                    redraw_pending = True
                    self.pixel_size = v
            elif k == 'detector_size':
                if (v != self.detector_size): 
                    redraw_pending = True
                    self.detector_size = v
                    self.beam_x = self.beam_y = self.detector_size/2
        if redraw_pending:
            self.update()
        return True
    
        
    def on_visibility_notify(self, widget, event):
        if event.get_state() == Gdk.VisibilityState.FULLY_OBSCURED:
            self._can_update = False
        else:
            self._can_update = True
            self.update()
        return True

    def on_unmap(self, widget):
        self._can_update = False
        return True
                
    def on_map(self, widget):
        self._can_update = True
        #self.update()
        return True
    
    def _angle(self, resol):
        sa = max(-1.0, min(0.5 * self.wavelength / resol, 1.0))
        return numpy.arcsin(sa)
        
    def _resol(self, angl):
        return 0.5 * self.wavelength / numpy.sin (angl)
        
    def _mm(self, pix, center):
        return (pix - center) * self.pixel_size
         
    def _shells(self, resolution=0.7, num=40):
        max_angle = self._angle( resolution )
        min_angle = self._angle( 50.0)
        step_size = ( max_angle - min_angle ) / num
        angles = numpy.arange(min_angle, max_angle + step_size, step_size)
        result = []
        for ang in angles:
            result.append( self._resol(ang) )
        return result

    def _pix_resol(self, xp, yp):
        x = (xp - self.beam_x) * self.pixel_size
        y = (yp - self.beam_y) * self.pixel_size
        dangle = numpy.arctan( numpy.sqrt(x**2 + (y*numpy.cos(self.two_theta) + self.distance*numpy.sin(self.two_theta))**2)
                 / (self.distance * numpy.cos(self.two_theta) - y * numpy.sin(self.two_theta)) )
        theta = 0.5 * ( dangle + 1.0e-12) # make sure theta is never zero
        d = self.wavelength / ( 2.0 * numpy.sin(theta) )
        return d

    def _do_calc(self):
        while not self._destroyed:
            if self._do_update:
                self._do_update = False
                grid_size = 150
                x = numpy.arange(0, self.detector_size, grid_size)
                y = x
                X,Y = numpy.meshgrid(x,y)
                Z = self._pix_resol(X,Y)
                xp = self._mm(X, self.beam_x)
                yp = self._mm(Y, self.beam_y)
                self.xp = xp
                self.yp = yp
                self.Z = Z
                GObject.idle_add(self.display)
            try:
                time.sleep(0.05)
            except:
                return
            
    def update(self, force=False):
        if self._can_update and self.get_child_visible():
            self._do_update = True
        return   
