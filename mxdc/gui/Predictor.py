"""
A Resolution Predictor widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
import gtk, gobject
import threading
import sys, time

from matplotlib.artist import Artist
from matplotlib.axes import Subplot
from matplotlib.figure import Figure
import matplotlib.cm as cm
from  matplotlib.colors import normalize
from matplotlib.numerix import arange, sin, pi, arcsin, arctan, sqrt, cos
from matplotlib.ticker import FormatStrFormatter
from pylab import meshgrid
from bcm.utils import *

try:
    from matplotlib.backends.backend_gtkcairo import FigureCanvasGTKCairo as FigureCanvas
except:
    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas

from matplotlib.backends.backend_gtk import NavigationToolbar2GTK as NavigationToolbar
            
class Predictor( gtk.Frame ):
    def __init__( self, pixel_size=0.07234, detector_size=3072 ):
        gtk.Frame.__init__(self)
        self.fig = Figure( figsize=( 6, 6 ), dpi=72, facecolor='w' )
        self.axis = self.fig.add_subplot(111, aspect='equal', xticks=[])
        self.canvas = FigureCanvas( self.fig )  # a gtk.DrawingArea
        self.add( self.canvas )
        self.set_shadow_type(gtk.SHADOW_IN)
        self.show_all()
        self.pixel_size = pixel_size
        self.detector_size = detector_size
        self.beam_x, self.beam_y = self.detector_size /2, self.detector_size /2
        self.two_theta = 0
        self.wavelength = 1.000
        self.last_updated = time.time()
        self.visible = True
        self.canvas.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
        self.canvas.connect('visibility-notify-event', self.on_visibility_notify)
        self.canvas.connect('unmap', self.on_unmap)

        
    def display(self, widget=None):
        self.axis.clear()
        cntr = self.axis.contour(self.xp, self.yp, self.Z, self.lines, linewidths=1)
        self.axis.clabel(cntr, inline=True, fmt='%1.1f',fontsize=9)        
        self.canvas.draw()
        return True
        
    def set_wavelength(self,wavelength):
        self.wavelength = wavelength
        return True
        
    def set_energy(self,energy):
        self.wavelength = keVToA(energy)
        return True
        
    def set_distance(self, distance):
        self.distance = distance
        return True
    
    def set_twotheta(self,twotheta):
        self.two_theta = twotheta
        return True
        
    def set_beam_center(self, beam_x, beam_y):
        self.beam_x = beam_x
        self.beam_y = beam_y
        
        
    def set_all(self, wavelength, distance, two_theta, beam_x=1535, beam_y=1535):
        self.wavelength = wavelength
        self.distance = distance
        self.two_theta = two_theta * pi/ 180.0
        self.beam_x = beam_x
        self.beam_y = beam_y
        return True
        
    def on_distance_changed(self, widget, distance):
        self.set_distance(distance)
        self.update()
        return True
        
    def on_two_theta_changed(self, widget, ang):
        self.set_twotheta(ang)
        self.update()
        return True
        
    def on_energy_changed(self, widget, val):
        self.set_energy(val)
        self.update()
        return True
        
    def on_visibility_notify(self, widget, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.visible = False
        else:
            self.visible = True
        return True

    def on_unmap(self, widget):
        self.visible = False
        return True
                
    def _angle(self, resol):
        return arcsin( 0.5 * self.wavelength / resol )
        
    def _resol(self, angl):
        return 0.5 * self.wavelength / sin (angl)
        
    def _mm(self, pix, center):
        return (pix - center) * self.pixel_size
         
    def _shells(self, resolution=0.9, num=8):
        max_angle = self._angle( resolution )
        min_angle = self._angle( 15.0)
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
        grid_size = 100
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
        elapsed_time = time.time() - self.last_updated
        if (elapsed_time < 1) and not force:
            pass
        elif (not self.visible):
            pass
        elif (self.wavelength*self.distance < 1.0):
            pass
        else:
            self.last_updated = time.time()
            calculator = threading.Thread(target=self._do_calc)
            calculator.start()
        return True
    