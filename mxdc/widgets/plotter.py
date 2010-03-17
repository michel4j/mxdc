"""
A Plotting widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""
import gtk, gobject
import sys, time, os
import pango
from matplotlib.artist import Artist
from matplotlib.axes import Subplot
from matplotlib.figure import Figure
import numpy
from matplotlib.ticker import FormatStrFormatter, MultipleLocator, MaxNLocator
from matplotlib import rcParams

from zope.interface import implements
from twisted.python.components import globalRegistry
from bcm.engine.scanning import IScanPlotter
#try:
#    from matplotlib.backends.backend_gtkcairo import FigureCanvasGTKCairo as FigureCanvas
#except:
#    from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas
#FIXME GTKCairo crashes sometimes on SL5.3 when that is sorted out, replace the following line with commented ones above
from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas
    
from matplotlib.backends.backend_gtk import NavigationToolbar2GTK as NavigationToolbar
from matplotlib.backends.backend_gtk import FileChooserDialog
try:
    from matplotlib import axes3d
except:
    from mpl_toolkits.mplot3d import axes3d

from misc import ActiveProgressBar
from bcm.engine import fitting

rcParams['legend.loc'] = 'best'
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class PlotterToolbar(NavigationToolbar):
    def __init__(self, canvas):
        self.toolitems = (
            ('Home', 'Reset original view', gtk.STOCK_HOME, 'home'),
            ('Back', 'Back to  previous view',gtk.STOCK_GO_BACK, 'back'),
            ('Forward', 'Forward to next view',gtk.STOCK_GO_FORWARD, 'forward'),
            ('Pan', 'Pan axes with left mouse, zoom with right', 'stock-tool-move.png','pan'),
            ('Zoom', 'Zoom to rectangle',gtk.STOCK_ZOOM_FIT, 'zoom'),
            (None, None, None, None),
            ('Save', 'Save the figure',gtk.STOCK_SAVE, 'save_figure'),
            ('Print', 'Print the figure', 'stock_print.png', 'print_figure'),
            )
        NavigationToolbar.__init__(self, canvas, None)
    
    def _init_toolbar2_2(self):
        basedir = matplotlib.rcParams['datapath']

        for text, tooltip_text, image_file, callback in self.toolitems:
            if text is None:
                 self.append_space()
                 continue
            if text in ['Pan','Print']:
                fname = os.path.join(DATA_DIR, image_file)
                image = gtk.Image()
                image.set_from_file(fname)
            else:
                image = gtk.Image()
                image.set_from_stock(image_file, gtk.ICON_SIZE_BUTTON)
                
            w = self.append_item(text,
                                 tooltip_text,
                                 'Private',
                                 image,
                                 getattr(self, callback)
                                 )

        self.append_space()

        self.message = gtk.Label()
        self.append_widget(self.message, None, None)
        self.message.show()

        self.fileselect = FileSelection(title='Save the figure',
                                        parent=self.win,)



    def _init_toolbar2_4(self):
        self.tooltips = gtk.Tooltips()

        for text, tooltip_text, stock, callback in self.toolitems:
            if text is None:
                self.insert( gtk.SeparatorToolItem(), -1 )
                continue
            tbutton = gtk.ToolButton()
            if text in ['Pan', 'Print']:
                fname = os.path.join(DATA_DIR, stock)
                image = gtk.Image()
                image.set_from_file(fname)
            else:
                image = gtk.Image()
                image.set_from_stock(stock, gtk.ICON_SIZE_BUTTON)
            tbutton.set_label_widget(image)
            self.insert(tbutton, -1)
            tbutton.connect('clicked', getattr(self, callback))
            tbutton.set_tooltip(self.tooltips, tooltip_text, 'Private')

        toolitem = gtk.SeparatorToolItem()
        self.insert(toolitem, -1)
        # set_draw() not making separator invisible,
        # bug #143692 fixed Jun 06 2004, will be in GTK+ 2.6
        toolitem.set_draw(False)
        toolitem.set_expand(True)

        toolitem = gtk.ToolItem()
        self.insert(toolitem, -1)
        self.message = gtk.Label()
        toolitem.add(self.message)

        self.show_all()

        self.fileselect = FileChooserDialog(
            title='Save the figure',
            parent=self.win,
            filetypes=self.canvas.get_supported_filetypes(),
            default_filetype=self.canvas.get_default_filetype()
            )
    
    def print_figure(self, obj):
        print 'No printing implemented'
          
class Plotter( gtk.Frame ):
    def __init__( self, loop=False, buffer_size=2500, xformat='%g' ):
        gtk.Frame.__init__(self)
        _fd = self.get_pango_context().get_font_description()
        rcParams['font.family'] = 'sans-serif'
        rcParams['font.sans-serif'] = _fd.get_family()
        rcParams['font.size'] = _fd.get_size()/pango.SCALE
        self.fig = Figure( figsize=( 10, 8 ), dpi=96, facecolor='w' )
        self.axis = []
        self.axis.append( self.fig.add_subplot(111) )
        self.xformatter = FormatStrFormatter(xformat)
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        self.axis[0].yaxis.tick_left()

        self.canvas = FigureCanvas( self.fig )  # a gtk.DrawingArea
        self.vbox = gtk.VBox()
        try:
            self.toolbar = PlotterToolbar(self.canvas)
        except:
            self.toolbar = NavigationToolbar(self.canvas, None)
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
        
        
    def add_line(self, xpoints, ypoints, pattern='', label='', ax=0, redraw=True ):
        assert( len(xpoints) == len(ypoints) )
        assert( ax < len(self.axis) )
        
        tmp_line, = self.axis[ax].plot( xpoints, ypoints, pattern, lw=1, 
                                        markersize=3, markerfacecolor='w',
                                        markeredgewidth=1, label=label)
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
        

    def clear(self, grid=False):
        self.fig.clear()
        self.axis = []    
        self.axis.append( self.fig.add_subplot(111) )
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        self.line = []
        self.x_data = []
        self.y_data = []
        
    def add_point(self, x, y, lin=0, redraw=True):
        if len(self.line) <= lin:
            self.add_line([x],[y],'-')
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
        self.axis[0].xaxis.set_major_locator(MaxNLocator(10))
        x_major = self.axis[0].xaxis.get_majorticklocs()
        dx_minor =  (x_major[-1]-x_major[0])/(len(x_major)-1) /5.
        self.axis[0].xaxis.set_minor_locator(MultipleLocator(dx_minor))
        self.axis[0].yaxis.tick_left()
        try:
            xmin, xmax = self.axis[0].xaxis.get_data_interval()
        except:
            xmin, xmax = self.axis[0].xaxis.get_data_interval().get_bounds()
        if (xmax - xmin) > 0.1:
            self.axis[0].set_xlim(xmin, xmax)
        #self.axis[0].legend()       
        self.canvas.draw()


class ScanPlotter(gtk.Window):
    implements(IScanPlotter)

 
    def __init__(self):
        gtk.Window.__init__(self)
        self.plotter = Plotter(self)
        self.plotter.set_size_request(577,400)
        vbox=gtk.VBox(False)
        vbox.pack_start(self.plotter, expand=True, fill=True)
        self.prog_bar = ActiveProgressBar()
        self.prog_bar.set_fraction(0.0)
        self.prog_bar.idle_text('0%')

        vbox.pack_start(self.prog_bar, expand=False, fill=False)
        globalRegistry.register([], IScanPlotter, '', self)
        self._sig_handlers = {}
        self.add(vbox)
        self.show_all()
        
    def connect_scanner(self, scan):
        _sig_map = {
            'started' : self.on_start, 
            'progress': self.on_progress, 
            'new-point': self.on_new_point, 
            'error': self.on_error, 
            'done': self.on_done, 
            'stopped': self.on_stop
        }
        
        # connect signals.
        scan.connect('started', self.on_start)
        scan.connect('new-point', self.on_new_point)
        scan.connect('progress', self.on_progress)
        scan.connect('done', self.on_done)
        scan.connect('error', self.on_error)
        scan.connect('error', self.on_stop)
                    
    
    def on_start(self, scan, data=None):
        """Clear Scan and setup based on contents of data dictionary."""
        self.plotter.clear()
        self._start_time = time.time()
        self.plotter.set_labels(title=scan.__doc__,
                                x_label=scan.data_names[0],
                                y1_label=scan.data_names[1])
             
    
    def on_progress(self, scan, fraction):
        """Progress handler."""
        elapsed_time = time.time() - self._start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        text = "ETA %s" % (time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        self.prog_bar.set_complete(fraction, text)

    def on_new_point(self, scan, data):
        """New point handler."""
        self.plotter.add_point(data[0], data[1])
        
        
    def on_stop(self, scan):
        """Stop handler."""
        self.prog_bar.set_text('Scan Stopped!')
    
    def on_error(self, scan, reason):
        """Error handler."""
        self.prog_bar.set_text('Scan Error: %s' % (reason,))
 
    def on_done(self, scan):
        """Done handler."""
        filename = scan.save()
        self.plot_file(filename)
    
    def plot_file(self, filename):
        """Do fitting and plot Fits"""
        image_filename = "%s.ps" % filename
        info = self._get_scan_data(filename)
        if info['scan_type'] == 'GridScan':
            data = info['data']
    
            xd = data[:,0]
            yd = data[:,1]
            zd = data[:,4]
    
            xlo = xd[0]
            xhi = xd[-1]
            ylo = yd[0]
            yhi = yd[-1]
    
            xmin = min(xd)
            xmax = max(xd)
            ymin = min(yd)
            ymax = max(yd)
    
            if info['dim'] != 0:
                szx = info['dim']
                szy = len(xd)/szx
            else:
                szx = int(numpy.sqrt(len(xd)))
                szy = szx
    
            x = numpy.linspace(xmin, xmax, szx)
            y = numpy.linspace(ymin, ymax, szy)
            z = zd.reshape(szy, szx)
            X,Y = numpy.meshgrid(x,y)
    
            if xlo > xhi:
                z = z[:,::-1]
            if ylo > yhi:
                    z = z[::-1,:]

            self.plotter.clear()
            ax = axes3d.Axes3D(self.plotter.fig)
            ax.set_title('%s\n%s' % (info['title'], info['subtitle']))
            ax.set_xlabel(info['x_label'])
            ax.set_ylabel(info['y_label'])
            ax.contour3D(X, Y, z, 50)
            self.plotter.canvas.draw()
            
        else:
            data = info['data']
            image_filename = "%s.ps" % filename
            xo = data[:,0]
            yo = data[:,-1]
    
            params = fitting.peak_fit(xo, yo, 'gaussian')
            yc = fitting.gauss(xo, params)
    
            fwhm = params[1]
            fwxl = [params[1]-0.5*fwhm, params[1]+0.5*fwhm]
            fwyl = [0.5 * params[0] + params[3], 0.5 * params[0] + params[3]]
            pkyl = [params[3],params[0]+params[3]]
            pkxl = [params[1],params[1]]
            
            #[ymax, fwhm, xpeak, x_hpeak[0], x_hpeak[1], cema]            
            histo_pars = fitting.histogram_fit(xo, yo)
            
            self.plotter.clear()
            ax = self.plotter.axis[0]
            ax.set_title('%s\n%s' % (info['title'], info['subtitle']))
            ax.set_xlabel(info['x_label'])
            ax.set_ylabel(info['y_label'])
            #ax.plot(xo,yo,'b-+')
            #ax.plot(xo,yc,'r--')
            self.plotter.add_line(xo, yo, pattern='b-+', redraw=False)
            self.plotter.add_line(xo, yc, pattern='r--', redraw=False)
            hh = 0.5 * (max(yo) - min(yo)) + min(yo)
            ax.plot([histo_pars[2], histo_pars[2]], [min(yo), max(yo)], 'b:')
            ax.plot([histo_pars[3], histo_pars[4]], [hh, hh], 'b:')
            
            # set font parameters for the ouput table
            fontpar = {}
            fontpar["family"]="monospace"
            fontpar["size"]=8
            info = "YMAX-fit = %11.4e\n" % params[0]
            info += "MIDP-fit = %11.4e\n" % params[2] 
            info += "FWHM-fit = %11.4e\n" % fwhm 
            self.plotter.fig.text(0.65,0.75, info,fontdict=fontpar, color='r')
            info = "YMAX-his = %11.4e\n" % histo_pars[0]
            info += "MIDP-his = %11.4e\n" % histo_pars[2] 
            info += "FWHM-his = %11.4e\n" % histo_pars[1]
            info += "CEMA-his = %11.4e\n" % histo_pars[5]
            self.plotter.fig.text(0.65,0.60, info,fontdict=fontpar, color='b')
            self.plotter.canvas.draw()
        
    def _get_scan_data(self, filename):
        lines = file(filename).readlines()
        title = lines[0].split(': ')[1][:-1]
        x_title = lines[2].split(': ')[1][:-1]
        y_title = lines[3].split(': ')[1][:-1]
        scan_type = title.split(' -- ')[0]
        data = numpy.loadtxt(filename, comments='#')
        t = os.stat(filename).st_ctime
        timestr = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.localtime(t))
        if scan_type == 'GridScan':
            #dim = int(lines[6].split(': ')[1][:-1])
            dim = 0
        else:
            dim = 0
        return {'scan_type': scan_type, 'x_label': x_title, 'y_label': y_title, 
            'title': title, 'data': data, 'subtitle': timestr, 'dim': dim}



    
