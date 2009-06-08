import threading
import logging
import gtk
import gobject
import gc

from zope.interface import Interface, Attribute
from zope.interface import implements
from twisted.python.components import globalRegistry
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from bcm.device.interfaces import IMotor, ICounter

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class ScanError(Exception):
    """Scan Error."""

class IScanPlotter(Interface):
    """Scan Plotter Object."""
    
    def connect_scan(self, scanner):
        """Connect handlers to scanner."""
        
    def on_start(scan, data):
        """Clear Scan and setup based on contents of info dictionary."""       
    
    def on_progress(scan, data):
        """Progress handler."""

    def on_new_point(scan, data):
        """New point handler."""
    
    def on_done(scan):
        """Done handler."""
    
    def on_stop(scan):
        """Stop handler."""
    
    def on_error(scan, error):
        """Error handler."""
        
        
class IScan(Interface):
    """Scan object."""
    
    data = Attribute("""Scan Data.""")
    
    def configure(**kw):
        """Configure the scan parameters."""
    
    def start():
        """Start the scan in asynchronous mode."""

    def run():
        """Run the scan in synchronous mode. Will block until complete"""
                 
    def stop():
        """Stop the scan.
        """
    
    def save(filename):
        """Save the scan data to the provided file name."""
                
class BasicScan(gobject.GObject):
    
    implements(IScan)
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['stopped'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
   

    def __init__(self):
        gobject.GObject.__init__(self)
        self._stopped = False
        self.data = []
        self.data_names = []
        try:
            self.plotter = globalRegistry.lookup([], IScanPlotter)
            self.plotter.connect_scanner(self)
        except:
            self.plotter = None
            _logger.info('No Plotter found.')
                
    def configure(self, **kwargs):
        self.data = []
        
    def start(self):
        self._stopped = False
        worker_thread = threading.Thread(target=self._thread_run)
        worker_thread.setDaemon(True)
        worker_thread.start()
        
    def _thread_run(self):
        ca.threads_init()
        self.run()
        pass
        
    def stop(self):
        self._stopped = True    

    def run(self):
        pass # derived classes should implement this
    
    def save(self, filename):
        try:
            f = open(filename,'w')
        except:
            self._logger.error("Could not open file '%s' for writing" % filename)
            return
        f.write('# Scan Type: %s -- %s\n' % (self.__class__.__name__, self.__class__.__doc__))
        f.write('# Column descriptions:\n')
        header = "#"
        for i , name in enumerate(self.data_names):
            f.write('#  Column %d: %s \n' % (i, name))
            header = "%s %14s" % (header, ('Column %d' % i) )  
        f.write('%s \n' % header)
        for point in self.data:
            for val in point:
                f.write('%15g' % val)
            f.write('\n')
        f.close()
        
    
class AbsScan(BasicScan):
    """An absolute scan of a single motor."""

    def __init__(self, mtr, start_pos, end_pos, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr, start_pos, end_pos, steps, cntr, t, i0)
        
    def configure(self, mtr, start_pos, end_pos, steps, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos = start_pos
        self._end_pos = end_pos
        
     
    def run(self):
        gobject.idle_add(self.emit, "started")
        step_size = (self._end_pos - self._start_pos) / float( self._steps )
        self.data_names = [self._motor.name, 
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        _logger.info("Scanning '%s' vs '%s' " % (self._motor.name, self._counter.name))
        _logger.info("%4s '%13s' '%13s_normalized' '%13s' '%13s'" % ('#',
                                                   self._motor.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        for i in xrange(self._steps+1):
            if self._stopped:
                _logger.info( "Scan stopped!" )
                break
            x = self._start_pos + (i * step_size)
            self._motor.move_to(x, wait=True)
            y = self._counter.count(self._duration)
            if self._i0 is not None:         
                i0 = self._i0.count(self._duration)
            else:
                i0 = 1.0
            self.data.append( [x, y/i0, i0, y] )
            _logger.info("%4d %15g %15g %15g %15g" % (i, x, y/i0, i0, y))
            gobject.idle_add(self.emit, "new-point", (x, y/i0, i0, y) )
            gobject.idle_add(self.emit, "progress", (i + 1.0)/(self._steps + 1.0) )
             
        gobject.idle_add(self.emit, "done")
    

class AbsScan2(BasicScan):
    """An Absolute scan of two motors."""
    
    def __init__(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0)
        
    def configure(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos1 = start_pos1
        self._end_pos1 = end_pos1 
        self._start_pos2 = start_pos2
        self._end_pos2 = end_pos2 
        
     
    def run(self):
        step_size1 = (self._end_pos1 - self._start_pos1) / float( self._steps )
        step_size2 = (self._end_pos2 - self._start_pos2) / float( self._steps )
        self.data_names = [self._motor1.name,
                           self._motor2.name,
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        _logger.info("Scanning '%s':'%s' vs '%s' " % (self._motor1.name,
                                                      self._motor2.name,
                                                      self._counter.name))
        _logger.info("%4s '%13s' '%13s' '%13s_normalized' '%13s' '%13s'" % ('#',
                                                   self._motor1.name,
                                                   self._motor2.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        for i in xrange(self._steps+1):
            if self._stopped:
                _logger.info( "Scan stopped!" )
                break
            x1 = self._start_pos1 + (i * step_size1)
            x2 = self._start_pos2 + (i * step_size2)
            self._motor1.move_to(x1)
            self._motor2.move_to(x2)
            self._motor1.wait()
            self._motor2.wait()
            y = self._counter.count(self._duration)         
            if self._i0 is not None:         
                i0 = self._i0.count(self._duration)
            else:
                i0 = 1.0
            self.data.append( [x1, x2, y/i0, i0, y] )
            _logger.info("%4d %15g %15g %15g %15g %15g" % (i, x1, x2, y/i0, i0, y))
            gobject.idle_add(self.emit, "new-point", (x1, x2, y/i0, i0, y) )
            gobject.idle_add(self.emit, "progress", (i + 1.0)/(self._steps + 1.0) )
             
        gobject.idle_add(self.emit, "done")


class RelScan(AbsScan):
    """A relative scan of a single motor."""
    
    def __init__(self, mtr, start_offset, end_offset, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr, start_offset, end_offset, steps, cntr, t, i0)

    def configure(self, mtr, start_offset, end_offset, steps, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        cur_pos = self._motor.get_position()
        self._start_pos = cur_pos + start_offset
        self._end_pos = cur_pos + end_offset

class RelScan2(AbsScan2):
    """A relative scan of a two motors."""
    
    def __init__(self, mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0)
    
    def configure(self, mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        cur_pos1 = self._motor1.get_position()
        cur_pos2 = self._motor2.get_position()
        self._start_pos1 = cur_pos1 + start_offset1
        self._end_pos1 = cur_pos1 + end_offset1
        self._start_pos2 = cur_pos2 + start_offset2
        self._end_pos2 = cur_pos2 + end_offset2 
        
class GridScan(BasicScan):
    """A absolute scan of two motors in a grid."""
    
    def __init__(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0)
        
    def configure(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos1 = start_pos1
        self._end_pos1 = end_pos1 
        self._start_pos2 = start_pos2
        self._end_pos2 = end_pos2 
        
     
    def run(self):
        step_size1 = (self._end_pos1 - self._start_pos1) / float( self._steps )
        step_size2 = (self._end_pos2 - self._start_pos2) / float( self._steps )
        self.data_names = [self._motor1.name,
                           self._motor2.name,
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        _logger.info("Scanning '%s':'%s' vs '%s' " % (self._motor1.name,
                                                      self._motor2.name,
                                                      self._counter.name))
        _logger.info("%4s '%13s' '%13s' '%13s_normalized' '%13s' '%13s'" % ('#',
                                                   self._motor1.name,
                                                   self._motor2.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        for i in xrange(self._steps*self._steps):
            if self._stopped:
                _logger.info( "Scan stopped!" )
                break
            i_1 = i % self._steps
            i_2 = i // self._steps
            x1 = self._start_pos1 + (i_1 * step_size1)
            x2 = self._start_pos2 + (i_2 * step_size2)
            self._motor1.move_to(x1)
            self._motor1.wait()
            self._motor2.move_to(x2)
            self._motor2.wait()
            y = self._counter.count(self._duration)         
            if self._i0 is not None:         
                i0 = self._i0.count(self._duration)
            else:
                i0 = 1.0
            self.data.append( [x1, x2, y/i0, i0, y] )
            _logger.info("%4d %15g %15g %15g %15g %15g" % (i, x1, x2, y/i0, i0, y))
            gobject.idle_add(self.emit, "new-point", (x1, x2, y/i0, i0, y) )
            gobject.idle_add(self.emit, "progress", (i + 1.0)/(self._steps + 1.0) )
             
        gobject.idle_add(self.emit, "done")



gobject.type_register(BasicScan)
