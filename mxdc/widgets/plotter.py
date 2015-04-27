"""
A Plotting widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""

from gi.repository import Gtk
from gi.repository import Pango
from matplotlib import rcParams
from matplotlib.backends.backend_gtk3 import FileChooserDialog
from matplotlib.backends.backend_gtk3 import NavigationToolbar2GTK3 as NavigationToolbar
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.colors import Normalize
from matplotlib.dates import MinuteLocator, SecondLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter
from misc import ActiveProgressBar
from mpl_toolkits.mplot3d import axes3d
from mxdc.engine import fitting
from mxdc.interface.engines import IScanPlotter
from twisted.python.components import globalRegistry
from zope.interface import implements
import numpy
import time, os


rcParams['legend.loc'] = 'best'
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class PlotterToolbar(NavigationToolbar):
    def __init__(self, canvas):
        self.toolitems = (
            ('Home', 'Reset original view', Gtk.STOCK_HOME, 'home'),
            ('Back', 'Back to  previous view',Gtk.STOCK_GO_BACK, 'back'),
            ('Forward', 'Forward to next view',Gtk.STOCK_GO_FORWARD, 'forward'),
            ('Pan', 'Pan axes with left mouse, zoom with right', Gtk.STOCK_FULLSCREEN,'pan'),
            ('Zoom', 'Zoom to rectangle',Gtk.STOCK_ZOOM_FIT, 'zoom'),
            (None, None, None, None),
            ('Save', 'Save the figure',Gtk.STOCK_SAVE, 'save_figure'),
            )
        NavigationToolbar.__init__(self, canvas, None)
    
    def _init_toolbar2_4(self):
        self.tooltips = Gtk.Tooltips()

        for text, tooltip_text, stock, callback in self.toolitems:
            if text is None:
                self.insert( Gtk.SeparatorToolItem(), -1 )
                continue
            tbutton = Gtk.ToolButton()
            image = Gtk.Image()
            image.set_from_stock(stock, Gtk.IconSize.BUTTON)
            tbutton.set_label_widget(image)
            self.insert(tbutton, -1)
            tbutton.connect('clicked', getattr(self, callback))
            tbutton.set_tooltip(self.tooltips, tooltip_text, 'Private')

        toolitem = Gtk.SeparatorToolItem()
        self.insert(toolitem, -1)
        # set_draw() not making separator invisible,
        # bug #143692 fixed Jun 06 2004, will be in GTK+ 2.6
        toolitem.set_draw(False)
        toolitem.set_expand(True)

        toolitem = Gtk.ToolItem()
        self.insert(toolitem, -1)
        self.message = Gtk.Label()
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

        
class Plotter(Gtk.Alignment):
    def __init__(self, loop=False, buffer_size=2500, xformat='%g', dpi=96 ):
        super(Plotter, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        _fd = self.get_pango_context().get_font_description()
        rcParams['legend.loc'] = 'best'
        rcParams['legend.fontsize'] = 8.5
        rcParams['legend.isaxes'] = False
        rcParams['figure.facecolor'] = 'white'
        rcParams['figure.edgecolor'] = 'white'
        self.fig = Figure( figsize=( 10, 8 ), dpi=dpi, facecolor='w' )
        self.axis = []
        self.axis.append( self.fig.add_subplot(111) )
        self.xformatter = FormatStrFormatter(xformat)
        self.axis[0].xaxis.set_major_formatter(self.xformatter)
        self.axis[0].yaxis.tick_left()

        self.canvas = FigureCanvas( self.fig )  # a Gtk.DrawingArea
        self.vbox = Gtk.VBox()
        try:
            self.toolbar = PlotterToolbar(self.canvas)
        except:
            self.toolbar = NavigationToolbar(self.canvas, None)
        self.vbox.pack_start( self.canvas , True, True, 0)
        self.vbox.pack_start( self.toolbar, False, False )
        self.line = []
        self.x_data = []
        self.y_data = []
        
        # variables used for grid plotting
        self.grid_data = None
        self.grid_mode = False
        self.grid_specs = None
        
        self.simulate_ring_buffer = loop
        self.buffer_size = buffer_size
        self.add(self.vbox)
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
        
    def set_time_labels(self, labels, fmt, maj_int, min_int):
        self.axis[0].xaxis.set_major_locator(MinuteLocator(interval=maj_int))
        self.axis[0].xaxis.set_minor_locator(SecondLocator(interval=min_int))
        if len(self.axis[0].xaxis.get_major_ticks()) < len(labels):
            labels.pop(0)
        self.axis[0].set_xticklabels([d is not ' ' and d.strftime(fmt) or '' for d in labels])   

    def clear(self, grid=False):
        self.fig.clear()
        self.axis = []    
        self.axis.append(self.fig.add_subplot(111))
        self.line = []
        self.x_data = []
        self.y_data = []
        self.grid_mode = grid
        if not self.grid_mode:
            self.grid_data = None
            self.grid_specs = None
            self.axis[0].xaxis.set_major_formatter(self.xformatter)
            
    
    def set_grid(self, data):        
        self.grid_data = numpy.zeros((data['steps'], data['steps']))
        self.grid_specs = data
        bounds = [data['start_1'], data['end_1'], data['start_2'], data['end_2']]
        self.grid_plot = self.axis[0].imshow(self.grid_data, interpolation='bicubic', 
                                             origin='lower', extent=bounds, aspect="auto")
       
    def add_grid_point(self, xv, yv, z, redraw=True):
        if self.grid_data is not None and self.grid_specs is not None:
            xl = numpy.linspace(self.grid_specs['start_1'], self.grid_specs['end_1'], self.grid_specs['steps'])
            yl = numpy.linspace(self.grid_specs['start_2'], self.grid_specs['end_2'], self.grid_specs['steps'])
            x = numpy.abs(xl-xv).argmin() # find index of value closest to xv
            y = numpy.abs(yl-yv).argmin() # find index of value closest to yv
            my, mx = self.grid_data.shape
            if (0 <= x < mx) and (0 <= y < my):
                self.grid_data[y,x] = z
                self.grid_plot.set_array(self.grid_data)
                self.grid_plot.set_norm(Normalize(vmin=self.grid_data.min(), vmax=self.grid_data.max()))
                self.canvas.draw()        
        return True

    def add_point(self, x, y, lin=0, redraw=True, resize=False):

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
            #curr_xmin, curr_xmax = self.line[lin].axes.get_xlim()
            
            ymin = resize and (ymin - ypadding) or (curr_ymin+ypadding < ymin) and curr_ymin  or (ymin - ypadding)
            ymax = resize and (ymax + ypadding) or (curr_ymax-ypadding > ymax) and curr_ymax  or (ymax + ypadding)

            if (xmax-xmin) > 1e-15:
                self.line[lin].axes.set_xlim(xmin, xmax)
                self.axis[0].xaxis.set_major_formatter(self.xformatter)    
            if (ymax -ymin)> 1e-15:
                self.line[lin].axes.set_ylim(ymin, ymax )
        
            if redraw:
                self.redraw()
        
        return True

    def redraw(self):
        self.axis[0].legend()       
        self.canvas.draw_idle()


class ScanPlotter(Gtk.VBox):
    implements(IScanPlotter)

 
    def __init__(self):
        GObject.GObject.__init__(self, False)
        self.plotter = Plotter(self)
        self.plotter.set_size_request(577,400)
        self.pack_start(self.plotter, expand=True, fill=True)
        self.prog_bar = ActiveProgressBar()
        self.prog_bar.set_fraction(0.0)
        self.prog_bar.idle_text('0%')

        self.pack_start(self.prog_bar, expand=False, fill=False)
        globalRegistry.register([], IScanPlotter, '', self)
        self._sig_handlers = {}
        self.show_all()
        self.fit = {}
        self.grid_scan = False
        
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
        data = scan.get_specs()
        if data.get('type','').lower() == 'grid':
            self.plotter.clear(grid=True)
            self.plotter.set_grid(data)
            self.grid_scan = True
        else:
            self.grid_scan = False
            self.plotter.clear()
        self._start_time = time.time()
        self.plotter.set_labels(title=scan.__doc__,
                                x_label=scan.data_names[0],
                                y1_label=scan.data_names[1])
             
    
    def on_progress(self, scan, fraction, msg):
        """Progress handler."""
        elapsed_time = time.time() - self._start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        #percent = fraction * 100
        text = "ETA %s" % (time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        self.prog_bar.set_complete(fraction, text)

    def on_new_point(self, scan, data):
        """New point handler."""

        if self.grid_scan:
            self.plotter.add_grid_point(data[0], data[1], data[2])
        else:
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
        #image_filename = "%s.ps" % filename
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
            #image_filename = "%s.ps" % filename
            xo = data[:,0]
            yo = data[:,-1]
    
            params, _ = fitting.peak_fit(xo, yo, 'gaussian')
            yc = fitting.gauss(xo, params)
    
            fwhm = params[1]
            #fwxl = [params[1]-0.5*fwhm, params[1]+0.5*fwhm]
            #fwyl = [0.5 * params[0] + params[3], 0.5 * params[0] + params[3]]
            #pkyl = [params[3],params[0]+params[3]]
            #pkxl = [params[1],params[1]]
            
            #[ymax, fwhm, xpeak, x_hpeak[0], x_hpeak[1], cema]            
            histo_pars, _ = fitting.histogram_fit(xo, yo)
            
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
            ax.set_xlim(min(xo), max(xo))
            
            # set font parameters for the ouput table
            fontpar = {}
            fontpar["family"]="monospace"
            fontpar["size"]=8
            info = "YMAX-fit = %11.4e\n" % params[0]
            info += "MIDP-fit = %11.4e\n" % params[2] 
            info += "FWHM-fit = %11.4e\n" % fwhm 
            print info
            self.plotter.fig.text(0.65,0.75, info,fontdict=fontpar, color='r')
            info = "YMAX-his = %11.4e\n" % histo_pars[0]
            info += "MIDP-his = %11.4e\n" % histo_pars[2] 
            info += "FWHM-his = %11.4e\n" % histo_pars[1]
            info += "CEMA-his = %11.4e\n" % histo_pars[5]
            self.plotter.fig.text(0.65,0.60, info,fontdict=fontpar, color='b')
            self.plotter.canvas.draw()
            print info
            self.fit['midp'] = params[2]
            self.fit['fwhm'] =  fwhm
            self.fit['ymax'] = params[0]
        
    def _get_scan_data(self, filename):
        lines = file(filename).readlines()
        title = lines[0].split(': ')[1][:-1]
        x_title = lines[3].split(': ')[1][:-1]
        y_title = lines[4].split(': ')[1][:-1]
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


class ScanPlotWindow(Gtk.Window):
    def __init__(self):
        GObject.GObject.__init__(self)
        self.plot = ScanPlotter()
        self.add(self.plot)
        self.show_all()
