
import threading
import time

import numpy
from gi.repository import GObject
from scipy import interpolate
from twisted.python.components import globalRegistry
from zope.interface import implements

from mxdc.com import ca
from mxdc.devices.interfaces import IMotor, ICounter
from mxdc.engines.interfaces import IScan, IScanPlotter
from mxdc.utils import json
from mxdc.utils import misc
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

class ScanError(Exception):
    """Scan Error."""

                
class BasicScan(GObject.GObject):
    
    implements(IScan)
    __gsignals__ = {}
    __gsignals__['new-point'] = (GObject.SignalFlags.RUN_FIRST, None, (object,))
    __gsignals__['progress'] = (GObject.SignalFlags.RUN_FIRST, None, (float, str,))
    __gsignals__['done'] = (GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['started'] = (GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['message'] = ( GObject.SignalFlags.RUN_FIRST, None, (str,))
    __gsignals__['busy'] = (GObject.SignalFlags.RUN_FIRST, None, (bool,))
    __gsignals__['error'] = ( GObject.SignalFlags.RUN_FIRST, None, (str,))
    __gsignals__['stopped'] = ( GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['paused'] = ( GObject.SignalFlags.RUN_FIRST, None, [object,bool])
   

    def __init__(self):
        GObject.GObject.__init__(self)
        self.stopped = False
        self.paused = False
        self.busy = False
        self._notify = False
        self.append = False
        self.config = {}
        self.data = []
        self.data_names = []
        try:
            self.plotter = globalRegistry.lookup([], IScanPlotter)
            self.plotter.connect_scanner(self)
        except:
            self.plotter = None
            #logger.debug('No TickerChart found.')

    def is_busy(self):
        return self.busy

    def configure(self, **kwargs):
        self.data = []
    
    def extend(self, steps):
        self.append = True

    def get_specs(self):
        return {}
        
    def start(self, append=None):
        self.stopped = False
        if append is not None and append:
            self.append = True
        if not self.append:
            self.data = []
        worker_thread = threading.Thread(target=self._thread_run)
        worker_thread.setDaemon(True)
        worker_thread.start()
        
    def _thread_run(self):
        self.busy = True
        GObject.idle_add(self.emit, 'message', 'Scan in progress')
        GObject.idle_add(self.emit, 'busy', True)
        ca.threads_init()
        self.run()
        self.busy = False
        GObject.idle_add(self.emit, 'busy', False)

    def pause(self, state):
        self.paused = state
        
    def stop(self):
        self.stopped = True

    def run(self):
        pass # derived classes should implement this

    def on_beam_change(self, obj, beam_available):
        self._notify = not beam_available
        if self._notify and (not self.paused) and (not self.stopped):
            self.pause(True)
    
    def save(self, filename=None):
        if filename is None:
            ext = self.__class__.__name__.lower()
            filename = time.strftime('%d%a-%H:%M:%S.') + ext
        try:
            f = open(filename,'w')
        except:
            logger.error("Could not open file '%s' for writing" % filename)
            return
        f.write('# Scan Type: %s -- %s\n' % (self.__class__.__name__, self.__class__.__doc__))
        f.write('# Meta Data: %s\n' % json.dumps(self.config))
        f.write('# Column descriptions: \n')
        header = ''
        for i , name in enumerate(self.data_names):
            f.write('#  Column %d: %s \n' % (i, name))
            header = "%s %14s" % (header, name )
        header = '#%s' % header[1:]
        f.write('%s \n' % header)
        for point in self.data:
            for val in point:
                f.write(' %14.8e' % val)
            f.write('\n')
        f.close()
        return filename
        
    
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
        self._step_size = (self._end_pos - self._start_pos) / float( self._steps )
        self._start_step = 0
    
    def extend(self, steps):
        self.append = True
        self._start_step = self._steps
        self._steps += steps
        
     
    def run(self):
        self.data_names = [self._motor.name, 
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        if not self.append:
            GObject.idle_add(self.emit, "started")
        logger.info("Scanning '%s' vs '%s' " % (self._motor.name, self._counter.name))
        logger.info("%4s '%8s' '%8s_norm' '%8s' '%8s'" % ('#',
                                                   self._motor.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        for i in xrange(self._start_step, self._steps):
            if self.stopped:
                logger.info( "Scan stopped!" )
                break
            x = self._start_pos + (i * self._step_size)
            self._motor.move_to(x, wait=True)
            if self._i0 is not None: 
                y,i0 = misc.multi_count(self._counter, self._i0, self._duration)        
            else:
                y = self._counter.count(self._duration)
                i0 = 1.0
            x = self._motor.get_position()
            self.data.append( [x, y/i0, i0, y] )
            logger.info("%4d %8g %8g %8g %8g" % (i, x, y/i0, i0, y))
            GObject.idle_add(self.emit, "new-point", (x, y/i0, i0, y) )
            GObject.idle_add(self.emit, "progress", (i + 1.0)/(self._steps), "" )
             
        GObject.idle_add(self.emit, "done")
    

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
        self._step_size1 = (self._end_pos1 - self._start_pos1) / float( self._steps )
        self._step_size2 = (self._end_pos2 - self._start_pos2) / float( self._steps )
        self._start_step = 0

    
    def extend(self, steps):
        self.append = True
        self._start_step = self._steps
        self._steps += steps
        
     
    def run(self):
        self.data_names = [self._motor1.name,
                           self._motor2.name,
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        if not self.append:
            GObject.idle_add(self.emit, "started")
        logger.info("Scanning '%s':'%s' vs '%s' " % (self._motor1.name,
                                                      self._motor2.name,
                                                      self._counter.name))
        logger.info("%4s '%13s' '%13s' '%13s_norm' '%13s' '%13s'" % ('#',
                                                   self._motor1.name,
                                                   self._motor2.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        for i in xrange(self._start_step, self._steps):
            if self.stopped:
                logger.info( "Scan stopped!" )
                break
            x1 = self._start_pos1 + (i * self._step_size1)
            x2 = self._start_pos2 + (i * self._step_size2)
            self._motor1.move_to(x1)
            self._motor2.move_to(x2)
            self._motor1.wait()
            self._motor2.wait()
            if self._i0 is not None:    
                y,i0 = misc.multi_count(self._counter, self._i0, self._duration)     
            else:
                y = self._counter.count(self._duration)  
                i0 = 1.0
            x1 = self._motor1.get_position()
            x2 = self._motor2.get_position()
            self.data.append( [x1, x2, y/i0, i0, y] )
            logger.info("%4d %15g %15g %15g %15g %15g" % (i, x1, x2, y/i0, i0, y))
            GObject.idle_add(self.emit, "new-point", (x1, x2, y/i0, i0, y) )
            GObject.idle_add(self.emit, "progress", (i + 1.0)/(self._steps), "")
             
        GObject.idle_add(self.emit, "done")


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
        self._step_size = (self._end_pos - self._start_pos) / float( self._steps )
        self._start_step = 0

class CntScan(BasicScan):
    """A Continuous scan of a single motor."""

    def __init__(self, mtr, start_pos, end_pos, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr, start_pos, end_pos, cntr, t, i0)
        
    def configure(self, mtr, start_pos, end_pos, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._start_pos = start_pos
        self._end_pos = end_pos
            
     
    def run(self):
        self.data_names = [self._motor.name, 
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        if not self.append:
            GObject.idle_add(self.emit, "started")
        logger.info("Scanning '%s' vs '%s' " % (self._motor.name, self._counter.name))
        logger.info("%4s '%8s' '%8s_norm' '%8s' '%8s'" % ('#',
                                                   self._motor.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        x_ot = []
        y_ot = []
        i_ot = []
        
        def _chg_cb(obj, dat):
            x_ot.append(dat)
        
        self._motor.move_to(self._start_pos, wait=True)
        self._motor.move_to(self._end_pos, wait=False)
        src_id = self._motor.connect('change', lambda x,y: x_ot.append((x.time_state, y)))
        self._motor.wait(start=True, stop=False)
        
        while self._motor.busy_state:
            if self.stopped:
                logger.info( "Scan stopped!" )
                break
            ts= time.time()
            y = self._counter.count(self._duration)
            t = (ts + time.time() / 2.0)

            if self._i0 is not None:         
                ts= time.time()
                i0 = self._i0.count(self._duration)
                ti = (ts + time.time() / 2.0)
            else:
                ti = time.time()
                i0 = 1.0
            y_ot.append((y, t))
            i_ot.append((i0, ti))
            yi = y/i0
            if len(x_ot) > 0:
                x = x_ot[-1][0] # x should be the last value, only rough estimate for now
                GObject.idle_add(self.emit, "new-point", (x, yi, i0, y))
                print "x", x
                print "start, end", self._start_pos, ",", self._end_pos
                GObject.idle_add(self.emit, "progress", (x - self._start_pos)/(self._end_pos - self._start_pos), "")
            time.sleep(0.01)
           
        self._motor.disconnect(src_id)
        # Perform interpolation
        print "x_ot", x_ot
        print "y_ot", y_ot
        print "i_ot", i_ot
        xi, tx = zip(*x_ot)
        yi, ty = zip(*y_ot)
        ii, ti = zip(*i_ot)

        mintx, maxtx = min(tx), max(tx)
        minty, maxty = min(ty), max(ty)
        tst = max(mintx, minty)
        ten = min(maxtx, maxty)
        t_final = numpy.linspace(tst, ten, len(y_ot)*2) # 2 x oversampling based on counter
        
        print "yi", yi
        print "ii", ii
        #tckx = interpolate.splrep(tx, xi)
        tcky = interpolate.splrep(ty, yi)
        tcki = interpolate.splrep(ti, ii)

        #xnew = interpolate.splev(t_final, tckx, der=0)
        ynew = interpolate.splev(tx, tcky, der=0)
        inew = interpolate.splev(tx, tcki, der=0)

        #print "xnew", xnew
        print "ynew", ynew
        print "inew", inew

        yinew = ynew/inew
        self.data = zip(xi, yinew, inew, ynew)          
        GObject.idle_add(self.emit, "done")


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
        self._step_size1 = (self._end_pos1 - self._start_pos1) / float( self._steps )
        self._step_size2 = (self._end_pos2 - self._start_pos2) / float( self._steps )
        self._start_step = 0
        
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
        self._points1 = numpy.linspace( self._start_pos1, self._end_pos1, self._steps)
        self._points2 = numpy.linspace( self._start_pos2, self._end_pos2, self._steps)
   
    def extend(self, steps):
        print 'Grid Scan can not be extended'


    def get_specs(self):
        return {'type': 'GRID',
                'steps' : self._steps,
                'start_1': self._start_pos1,
                'start_2': self._start_pos2,
                'end_1': self._end_pos1,
                'end_2': self._end_pos2,
                }
     
    def run(self):
        self.data_names = [self._motor1.name,
                           self._motor2.name,
                           self._counter.name+'_scaled', 
                           'I_0',
                           self._counter.name]
        GObject.idle_add(self.emit, "started")
        logger.info("Scanning '%s':'%s' vs '%s' " % (self._motor1.name,
                                                      self._motor2.name,
                                                      self._counter.name))
        logger.info("%4s '%13s' '%13s' '%13s_normalized' '%13s' '%13s'" % ('#',
                                                   self._motor1.name,
                                                   self._motor2.name,
                                                   self._counter.name,
                                                   'I_0',
                                                   self._counter.name))
        total_points = len(self._points1) * len(self._points2)
        pos = 0
        for x2 in self._points2:
            for x1 in self._points1:
                if self.stopped:
                    logger.info( "Scan stopped!" )
                    break
                self._motor2.move_to(x2)
                self._motor2.wait()
                self._motor1.move_to(x1)
                self._motor1.wait()

                if self._i0 is not None:         
                    y,i0 = misc.multi_count(self._counter, self._i0, self._duration)
                else:
                    y = self._counter.count(self._duration)
                    i0 = 1.0
                self.data.append( [x1, x2, y/i0, i0, y] )
                logger.info("%4d %15g %15g %15g %15g %15g" % (pos, x1, x2, y/i0, i0, y))
                GObject.idle_add(self.emit, "new-point", (x1, x2, y/i0, i0, y) )
                GObject.idle_add(self.emit, "progress", (pos + 1.0)/(total_points), "" )
                pos += 1
             
        GObject.idle_add(self.emit, "done")


