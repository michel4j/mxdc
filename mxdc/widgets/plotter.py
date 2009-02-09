"""
A Plotting widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
import gtk, gobject
import sys, time
import pango

from matplotlib.artist import Artist
from matplotlib.axes import Subplot
from matplotlib.figure import Figure
from matplotlib.numerix import arange, sin, pi
from matplotlib.ticker import FormatStrFormatter, MultipleLocator
from matplotlib import rcParams

try:
    from matplotlib.backends.backend_gtkcairo import FigureCanvasGTKCairo as FigureCanvas
except:
    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas
    
from matplotlib.backends.backend_gtk import NavigationToolbar2GTK as NavigationToolbar


rcParams['legend.loc'] = 'best'

class Plotter( gtk.Frame ):
    def __init__( self, loop=False, buffer_size=2500, xformat='%0.1f' ):
        gtk.Frame.__init__(self)
        _fd = self.get_pango_context().get_font_description()
        rcParams['font.family'] = _fd.get_family()
        rcParams['font.size'] = _fd.get_size()/pango.SCALE
        self.fig = Figure( figsize=( 10, 8 ), dpi=96, facecolor='w' )
        self.axis = []
        self.axis.append( self.fig.add_subplot(111) )
        self.xformatter = FormatStrFormatter(xformat)
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        self.axis[0].yaxis.tick_left()

        self.canvas = FigureCanvas( self.fig )  # a gtk.DrawingArea
        self.vbox = gtk.VBox()
        self.toolbar = NavigationToolbar( self.canvas, None )
        self.vbox.pack_start( self.canvas )
        self.vbox.pack_start( self.toolbar, False, False )
        self.line = []
        self.x_data = []
        self.y_data = []
        self.simulate_ring_buffer = loop
        self.buffer_size = buffer_size
        self.add(self.vbox)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.show_all()
        

        
    def add_line(self, xpoints, ypoints, pattern='', ax=0, redraw=True ):
        assert( len(xpoints) == len(ypoints) )
        assert( ax < len(self.axis) )
        
        tmp_line, = self.axis[ax].plot( xpoints, ypoints, pattern, lw=1)
        self.line.append( tmp_line )

        self.x_data.append( list(xpoints) )
        self.y_data.append( list(ypoints) )
        
        # adjust axes limits as necessary
        lin = len(self.line) - 1
        ymin = min(self.y_data[lin])
        ymax = max(self.y_data[lin])
        if len(self.x_data[lin]) > 1:
            for i in range( len(self.line) ):
                mx = max(self.x_data[i])
                mn = min(self.x_data[i])
                if i == 0:
                    xmax, xmin = mx, mn
                else:
                    xmax = (xmax > mx) and xmax or mx
                    xmin = (xmin < mn) and xmin or mn
            self.line[lin].axes.set_xlim(xmin, xmax) 
            self.line[lin].axes.xaxis.set_major_formatter(self.xformatter)    
        ypadding = (ymax - ymin)/8.0  # pad 1/8 of range to either side
            
        #only update limits if they are wider than current limits
        curr_ymin, curr_ymax = self.line[lin].axes.get_ylim()
        ymin = (curr_ymin+ypadding < ymin) and curr_ymin  or (ymin - ypadding)
        ymax = (curr_ymax-ypadding > ymax) and curr_ymax  or (ymax + ypadding)
        
        self.line[lin].axes.set_ylim(ymin, ymax )
        if redraw:
            self.canvas.draw()
        return True
        
    def add_axis(self, label=""):
        ax = self.fig.add_axes(self.axis[0].get_position(), 
            sharex=self.axis[0], 
            frameon=False)
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_ylabel(label)
        for label in ax.get_xticklabels():
            label.set_visible(False)
        self.axis.append( ax )
        return len(self.axis) - 1
    
    def set_labels(self, title="", x_label="", y1_label=""):
        self.axis[0].set_title(title)
        self.axis[0].set_xlabel(x_label)
        self.axis[0].set_ylabel(y1_label)

    def clear(self):
        self.fig.clear()
        self.axis = []    
        self.axis.append( self.fig.add_subplot(111) )
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        self.line = []
        self.x_data = []
        self.y_data = []
        
    def add_point(self, x, y, lin=0, redraw=True):
        if len(self.line) <= lin:
            self.add_line([x],[y],'-+')
        else:                    
            # when using ring buffer, remove first element before adding if full
            if self.simulate_ring_buffer and len(self.x_data[lin]) == self.buffer_size:
                self.x_data[lin] = self.x_data[lin][1:]
                self.y_data[lin] = self.y_data[lin][1:]
        
            # add points to end of line        
            self.x_data[lin].append(x)
            self.y_data[lin].append(y)
            # update the line data
            self.line[lin].set_data(self.x_data[lin],self.y_data[lin])

            # adjust axes limits as necessary
            ymin = min(self.y_data[lin])
            ymax = max(self.y_data[lin])
            xmin = min(self.x_data[lin])
            xmax = max(self.x_data[lin])
            ypadding = (ymax - ymin)/8.0  # pad 1/8 of range to either side
            
            #only update limits if they are wider than current limits
            curr_ymin, curr_ymax = self.line[lin].axes.get_ylim()
            curr_xmin, curr_xmax = self.line[lin].axes.get_xlim()
            ymin = (curr_ymin+ypadding < ymin) and curr_ymin  or (ymin - ypadding)
            ymax = (curr_ymax-ypadding > ymax) and curr_ymax  or (ymax + ypadding)

            if (xmax-xmin) > 1e-15:
                self.line[lin].axes.set_xlim(xmin, xmax)
                self.axis[0].xaxis.set_major_formatter(self.xformatter)    
            if (ymax -ymin)> 1e-15:
                self.line[lin].axes.set_ylim(ymin, ymax )
        
            if redraw:
                self.redraw()
        
        return True

    def redraw(self):
        x_major = self.axis[0].xaxis.get_majorticklocs()
        dx_minor =  (x_major[-1]-x_major[0])/(len(x_major)-1) /5.
        self.axis[0].xaxis.set_minor_locator(MultipleLocator(dx_minor))         
        self.canvas.draw()    

