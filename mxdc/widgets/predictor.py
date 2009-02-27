"""
A Resolution Predictor widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
import gtk, gobject
import threading
import sys, time
import pango

from matplotlib.artist import Artist
from matplotlib.axes import Subplot
from matplotlib.figure import Figure
import matplotlib.cm as cm
from matplotlib.colors import normalize
from matplotlib.numerix import arange, sin, pi, arcsin, arctan, sqrt, cos
from matplotlib.ticker import FormatStrFormatter
from matplotlib import rcParams
from pylab import meshgrid
from bcm.utils import converter
from bcm.utils.log import get_module_logger

_logger = get_module_logger(__name__)

try:
    from matplotlib.backends.backend_gtkcairo import FigureCanvasGTKCairo as FigureCanvas
except:
    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas

from matplotlib.backends.backend_gtk import NavigationToolbar2GTK as NavigationToolbar
            
class Predictor( gtk.AspectFrame ):
    def __init__( self, pixel_size=0.07234, detector_size=3072):
        gtk.AspectFrame.__init__(self, obey_child=True, ratio=1.0)
        self.fig = Figure( figsize=(8,8), dpi=80, facecolor='w')
        self.axis = self.fig.add_axes([0.02,0.02,0.96,0.96], aspect='equal')
        _fd = self.get_pango_context().get_font_description()
        rcParams['font.family'] = _fd.get_family()
        rcParams['font.size'] = _fd.get_size()/pango.SCALE
        
        self.canvas = FigureCanvas( self.fig )  # a gtk.DrawingArea
        self.add( self.canvas )
        self.set_shadow_type(gtk.SHADOW_ETCHED_OUT)
        self.show_all()
        self.pixel_size = pixel_size
        self.detector_size = detector_size
        self.beam_x, self.beam_y = self.detector_size /2, self.detector_size /2
        self.two_theta = 0
        self.wavelength = 1.000
        self.distance = 250.0
        self.last_updated = 0
        self._can_update = True
        self.canvas.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
        self.canvas.connect('visibility-notify-event', self.on_visibility_notify)
        self.canvas.connect('unmap', self.on_unmap)
        self.canvas.connect_after('map', self.on_map)
        self._do_update = False

        calculator = threading.Thread(target=self._do_calc)
        calculator.setDaemon(True)
        calculator.start()
        

        
    def display(self, widget=None):
        self.axis.clear()
        self.axis.set_axis_off()
        normFunction = normalize(-3, 8)
        cntr = self.axis.contour(self.xp, self.yp, self.Z, self.lines, linewidths=1, cmap=cm.hot_r, norm=normFunction)
        #cntr = self.axis.contour(self.xp, self.yp, self.Z, 16)
        self.axis.clabel(cntr, inline=True, fmt='%1.1f',fontsize=9)        
        self.canvas.draw()
        _logger.debug('Predictor Widget updating...')
        self.last_updated = time.time()
        return False
        
    def configure(self, **kwargs):
        redraw_pending = False
        for k, v in kwargs.items():
            if k == 'wavelength':
                if (abs(v-self.wavelength) > 0.1): 
                    redraw_pending = True
                    self.wavelength = v
            elif k == 'energy':
                v_ = converter.energy_to_wavelength(v)
                if (abs(v_-self.wavelength) >= 0.1): 
                    redraw_pending = True
                    self.wavelength = v_
            elif k == 'distance':
                if (abs(v-self.distance) >= 1.0): 
                    redraw_pending = True
                self.distance = v
            elif k == 'two_theta':
                v_ = v * pi/ 180.0
                if (abs(v_-self.two_theta) >= 0.05):
                    redraw_pending = True
                    self.two_theta = v_
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
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self._can_update = False
        else:
            self._can_update = True
            self.update()
        return True

    def on_unmap(self, widget):
        self._can_update = False
        self._do_update = False
        return True
                
    def on_map(self, widget):
        self._can_update = True
        self._do_update = False
        self.update(force=True)
        return True
    
    def _angle(self, resol):
        return arcsin( 0.5 * self.wavelength / resol )
        
    def _resol(self, angl):
        return 0.5 * self.wavelength / sin (angl)
        
    def _mm(self, pix, center):
        return (pix - center) * self.pixel_size
         
    def _shells(self, resolution=0.9, num=8):
        max_angle = self._angle( resolution )
        min_angle = self._angle( 25.0)
        step_size = ( max_angle - min_angle ) / num
        angles = arange(min_angle, max_angle + step_size, step_size)
        result = []
        for ang in angles:
            result.append( self._resol(ang) )
        return result

    def _pix_resol(self, xp, yp):
        x = (xp - self.beam_x) * self.pixel_size
        y = (yp - self.beam_y) * self.pixel_size
        dangle = arctan( sqrt(x**2 + pow(y*cos(self.two_theta) + self.distance*sin(self.two_theta),2))
                 / (self.distance * cos(self.two_theta) - y * sin(self.two_theta)) )
        theta = 0.5 * ( dangle + 1.0e-12) # make sure theta is never zero
        d = self.wavelength / ( 2.0 * sin(theta) )
        return d

    def _do_calc(self):
        while 1:
            while not self._do_update:
                time.sleep(1.0)
            self._do_update = False
            grid_size = 50
            x = arange(0, self.detector_size, grid_size)
            y = x
            X,Y = meshgrid(x,y)
            Z = self._pix_resol(X,Y)
            xp = self._mm(X, self.beam_x)
            yp = self._mm(Y, self.beam_y)
            lines = self._shells(num=16)
            self.xp = xp
            self.yp = yp
            self.Z = Z
            self.lines = lines
            gobject.idle_add(self.display)

    def update(self, force=False):
        if self._can_update and self.get_child_visible():
            self._do_update = True
        return
    
