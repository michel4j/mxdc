#!/usr/bin/env python
"""
A Plotting widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
import gtk, gobject
import sys, time

from matplotlib.artist import Artist
from matplotlib.axes import Subplot
from matplotlib.figure import Figure
from matplotlib.numerix import arange, sin, pi
from matplotlib.ticker import FormatStrFormatter
from pylab import delaxes

#try:
#    from matplotlib.backends.backend_gtkcairo import FigureCanvasGTKCairo as FigureCanvas
#except:
from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas
from matplotlib.backends.backend_gtk import NavigationToolbar2GTK as NavigationToolbar

class Plotter( gtk.Frame ):
    def __init__( self, loop=False, buffer_size=500 ):
        gtk.Frame.__init__(self)
        self.fig = Figure( figsize=( 10, 8 ), dpi=100, facecolor='w' )
        self.axis = []
        self.axis.append( self.fig.add_subplot(111) )
        self.xformatter = FormatStrFormatter('%0.4g')
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        #self.axis[-1].yaxis.tick_left()
        #self.axis[-1].yaxis.set_label_position('left')
        
    
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
        self.set_shadow_type(gtk.SHADOW_IN)
        self.show_all()
        

        
    def add_line(self, xpoints, ypoints, pattern='', ax=0, redraw=True, autofit=True):
        assert( len(xpoints) == len(ypoints) )
        assert( ax < len(self.axis) )
        
        tmp_line, = self.axis[ax].plot( xpoints, ypoints, pattern, lw=1 )
        self.line.append( tmp_line )

        self.x_data.append( list(xpoints) )
        self.y_data.append( list(ypoints) )
        
        if autofit:
            # adjust axes limits as necessary
            lin = len(self.line) - 1
            if len(self.x_data[lin]) > 0:
                for i in range( len(self.y_data) ):
                    mxx = max(self.x_data[i])
                    mnx = min(self.x_data[i])
                    mxy = max(self.y_data[i])
                    mny = min(self.y_data[i])
                    
                    if i == 0:
                        xmax, xmin = mxx, mnx
                        ymax, ymin = mxy, mny
                    else:
                        xmax = (xmax > mxx) and xmax or mxx
                        xmin = (xmin < mnx) and xmin or mnx
                        ymax = (ymax > mxy) and ymax or mxy
                        ymin = (ymin < mny) and ymin or mny
                self.line[lin].axes.set_xlim(xmin, xmax) 
                self.line[lin].axes.xaxis.set_major_formatter(self.xformatter)    
                ypadding = (ymax - ymin)/8.0  # pad 1/8 of range to either side
                ymin = ymin - ypadding
                ymax = ymax + ypadding
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
        ax.xaxis.set_major_formatter(self.xformatter)    
        self.axis.append( ax )
        return len(self.axis) - 1
    
    def set_labels(self, title="", x_label="", y1_label=""):
        self.axis[0].set_title(title)
        self.axis[0].set_xlabel(x_label)
        self.axis[0].set_ylabel(y1_label)

    def clear(self):
        self.axis[0].clear()
        for ax in self.axis[1:]:
            self.fig.delaxes(ax)
            
        self.line = []
        self.x_data = []
        self.y_data = []
        
    def add_point(self, x, y, lin=0, redraw=True):
        if len(self.line) <= lin:
            self.add_line([x],[y],'+-')
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
                # when using ring buffer, always update x-limits
            if self.simulate_ring_buffer:
                xmin = (curr_xmin < xmin) and curr_xmin  or xmin
                xmax = curr_xmax > xmax and curr_xmax  or xmax

            self.line[lin].axes.set_xlim(xmin, xmax)
            self.line[lin].axes.set_ylim(ymin, ymax )
            self.line[lin].axes.xaxis.set_major_formatter(self.xformatter)    
        
        if redraw:
            self.canvas.draw()
        
        return True
    

