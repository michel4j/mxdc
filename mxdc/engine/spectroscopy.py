"""This module defines classes aid interfaces for X-Ray fluorescence."""
from mxdc.interface.beamlines import IBeamline
from mxdc.engine.autochooch import AutoChooch
from mxdc.engine.scanning import BasicScan, ScanError
from mxdc.service.utils import  send_array
from mxdc.utils import science, json, converter
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_short_uuid, multi_count
from mxdc.utils.science import *
from datetime import datetime
from twisted.python.components import globalRegistry
from zope.interface import Interface, Attribute, invariant
from gi.repository import GObject
import os
import re
import time


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class XRFScan(BasicScan):    
    def __init__(self, energy=None, edge='Se-K', t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self.data_names = ['Energy', 'Counts']
        self.configure(t, energy, edge, attenuation, directory, 'xrf')
        
    def configure(self, energy, edge, t, attenuation, directory, prefix, crystal=None, uname=None):
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        self.scan_parameters = {}
        self.scan_parameters['energy'] = energy
        self.scan_parameters['edge'] = edge
        self.scan_parameters['duration'] = t
        self.scan_parameters['directory'] = directory
        self.scan_parameters['prefix'] = prefix
        self.scan_parameters['user_name'] = uname
        self.scan_parameters['filename'] = os.path.join(directory, "%s_%0.3f.raw" % (prefix, energy))
        self.scan_parameters['results_file'] = os.path.join(directory, "%s_%0.3f.out" % (prefix, energy))
        self.scan_parameters['attenuation'] = attenuation
        self.scan_parameters['crystal_id'] = crystal
        self.meta_data = {'energy': energy, 'time': t, 'attenuation': attenuation, 'prefix': prefix, 'user_name': uname}
        self.results = {}
        
    def analyse(self):        
        x = self.data[:,0].astype(float)
        y = self.data[:,1].astype(float)
        energy = self._energy
        sel = (x < 0.5) | (x > energy - 0.5*self.beamline.config.get('xrf_energy_offset', 2.0))
        y[sel] = 0.0
        
        # set FWHM of detector
        science.PEAK_FWHM = self.beamline.config.get('xrf_fwhm', 0.1)
        
        elements, bblocks, coeffs = science.interprete_xrf(x, y, energy)
        assigned = {}        
        for i, el_info in enumerate(elements):
            symbol = el_info[0]
            if coeffs[i] > 0.001: 
                prob = 100.0*bblocks[:,i].sum()/y.sum()
                if prob > 0.1:
                    line_info = science.get_line_info(el_info, coeffs[i])
                    if line_info is not None:
                        assigned[symbol] = [prob, science.get_line_info(el_info, coeffs[i])]         
        
        # twisted does not like numpy.float64 so we need to convert x, y to native python
        # floats here
        ys = science.smooth_data(y, times=2, window=21)
        self.results = {
            'data': {'energy': map(float, list(x)), 
                     #'counts': map(float, list(self.data[:,1])),
                     'counts': map(float, list(ys)),
                     'fit' : map(float, list(bblocks.sum(1)))},
            'assigned': assigned,
            'parameters': {'directory': self._directory,
                            'energy': self._energy,
                            'edge': self._edge,
                            'exposure_time': self._duration,
                            'output_file': self._filename,
                            'attenuation': self._attenuation,
                            'crystal_id': self._crystal_id,
                            'prefix': self._prefix },
            'kind': 1, # Excitation Scan
            }
        fp = open(self._results_file, 'w')
        json.dump(self.results, fp)
        fp.close()
        
        
        
    def run(self):
        self._paused = False
        _logger.debug('Excitation Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        # get parameters from recent configure
        self._energy = self.scan_parameters['energy']
        self._edge = self.scan_parameters['edge']
        self._duration = self.scan_parameters['duration']
        self._directory = self.scan_parameters['directory']
        self._prefix = self.scan_parameters['prefix']
        self._crystal_id = self.scan_parameters['crystal_id']
        self._user_name = self.scan_parameters['user_name']
        self._filename = self.scan_parameters['filename']
        self._results_file = self.scan_parameters['results_file']
        self._attenuation = self.scan_parameters['attenuation']
        self.data = []        
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            _logger.debug('Exitation Scan started.')
            GObject.idle_add(self.emit, 'started')   
            # prepare environment for scannning
            GObject.idle_add(self.emit, "progress", -1, "Preparing devices ...")
            self.beamline.goniometer.set_mode('SCANNING')
            GObject.idle_add(self.emit, "progress", -1, "Cooling down MCA ...")            
            self.beamline.mca.configure(retract=True, cooling=True, energy=None)
            self.beamline.attenuator.set(self._attenuation)
            if self._energy is not None:
                _cur_energy = self.beamline.energy.get_position()
                GObject.idle_add(self.emit, "progress", -1, "Changing Energy ...")
                self.beamline.energy.move_to(self._energy)
                self.beamline.energy.wait()
                
#                 # if energy just moved more than 5eV, optimize
#                 if abs(_cur_energy - self._energy) >= 0.005:
#                     GObject.idle_add(self.emit, "progress", -1, "Optimizing beam ...")
#                     self.beamline.mostab.start()
#                     self.beamline.mostab.wait()

            GObject.idle_add(self.emit, "progress", -1, "Acquiring spectrum ...")
            self.beamline.exposure_shutter.open()
            self.data = self.beamline.mca.acquire(t=self._duration)
            self.beamline.exposure_shutter.close()
            self.save(self._filename)
            GObject.idle_add(self.emit, "progress", -1, 'Interpreting spectrum ...')
            self.analyse()
            GObject.idle_add(self.emit, "done")
            GObject.idle_add(self.emit, "progress", 1.0, 'Done')
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.mca.configure(retract=False)
            _logger.debug('Excitation scan done.')
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.lock.release()
        return self.results
            

class XANESScan(BasicScan):
    def __init__(self, edge='Se-K', t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self._energy_db = get_energy_database()
        self.autochooch = AutoChooch()
        self.configure(edge, t, attenuation, directory, 'xanes')
        
    def configure(self, edge, t, attenuation, directory, prefix, crystal=None, uname=None):
        #FIXME: Possible race condition here if new configure is issued while previous scan is still running
        # - maybe we should use queues and have the scan constantly check and perform a scan
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        try:
            self.beamline.storage_ring.disconnect(self.beam_connect)
        except:
            pass
        self.beam_connect = self.beamline.storage_ring.connect('beam', self.on_beam_change)
        self.scan_parameters = {}
        self.scan_parameters['edge'] = edge
        self.scan_parameters['edge_energy'],  self.scan_parameters['roi_energy'] = self._energy_db[edge]
        self.scan_parameters['duration'] = t
        self.scan_parameters['directory'] = directory
        self.scan_parameters['prefix'] = prefix
        self.scan_parameters['user_name'] = uname
        self.scan_parameters['targets'] = xanes_targets(self.scan_parameters['edge_energy'])
        self.scan_parameters['filename'] = os.path.join(directory, "%s_%s.raw" % (prefix, edge))
        self.scan_parameters['attenuation'] = attenuation
        self.scan_parameters['crystal_id'] = crystal
        self.meta_data = {'edge': edge, 'time': t, 'attenuation': attenuation, 'prefix': prefix, 'user_name': uname}
        
                    
    def analyse_file(self, filename):
        data = numpy.loadtxt(filename)
        raw_text = file(filename).read()
        self.data = zip(data[:,0], data[:,1], data[:,2], data[:,3])
        
        meta = re.search('# Meta Data: ({.+})', raw_text)
        if meta:
            self.meta_data = json.loads(meta.group(1))
            self._edge = self.meta_data['edge']
            self._directory = os.path.dirname(filename)
            self._prefix = self.meta_data['prefix']
            self._user_name = self.meta_data['user_name']
                        
        self.analyse()
        GObject.idle_add(self.emit, "done")
    
    def analyse(self):
        self.autochooch.configure(self._edge, self._directory, self._prefix, self._user_name)
        success = self.autochooch.run()
        res_data = {'energy': [float(v[0]) for v in self.data], 
                    'counts': [float(v[1]) for v in self.data]}
        if success:
            _efs = self.autochooch.data
            efs_data = {'energy': map(float, _efs[:,0]),
                        'fp': map(float, _efs[:,2]), 
                        'fpp': map(float, _efs[:,1])
                        }
            self.results = {
                'data': res_data,
                'efs': efs_data,
                'energies': self.autochooch.results,
                'text': self.autochooch.results_text,
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self._prefix, self._edge),
                'directory': self._directory,
                'edge': self._edge,
                'crystal_id': self._crystal_id,
                'attenuation': self._attenuation,
                'energy': self._edge_energy,
                'kind': 0 # MAD Scan
                }
        else:
            GObject.idle_add(self.emit, 'error', 'Analysis Failed')
            self.results = {
                'data': res_data,
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self._prefix, self._edge),
                'directory': self._directory}
         
        
    def run(self):
        self._paused = False
        _logger.info('Edge Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()

        # Obtain scan parameters from recent configure
        self._duration = self.scan_parameters['duration']
        self._edge = self.scan_parameters['edge']
        self._edge_energy = self.scan_parameters['edge_energy']
        self._roi_energy = self.scan_parameters['roi_energy']      
        self._targets = self.scan_parameters['targets']        
        self._attenuation = self.scan_parameters['attenuation']
        self._directory = self.scan_parameters['directory']
        self._prefix = self.scan_parameters['prefix']
        self._user_name = self.scan_parameters['user_name']
        self._filename = self.scan_parameters['filename']
        self._crystal_id = self.scan_parameters['crystal_id']
        self.data = []
        self.chooch_results = {} 
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            GObject.idle_add(self.emit, 'started')
            _logger.info('Edge scan started.')
            self.beamline.goniometer.set_mode('SCANNING')
            GObject.idle_add(self.emit, "progress", -1, "Preparing devices ...")
            self.beamline.attenuator.set(self._attenuation)
            GObject.idle_add(self.emit, "progress", -1, "Cooling down MCA ...")            
            self.beamline.mca.configure(retract=True, cooling=True, energy=self._roi_energy)
            GObject.idle_add(self.emit, "progress", -1, "Moving to Edge ...")
            _cur_energy = self.beamline.energy.get_position()
            self.beamline.energy.move_to(self._edge_energy)
            self.beamline.energy.wait()
            self.beamline.bragg_energy.wait()
            GObject.idle_add(self.emit, "progress", -1, "Stabilizing beam ...")
            time.sleep(5)
#             # if energy just moved more than 10eV, optimize
#             if abs(_cur_energy - self._edge_energy) >= 0.01:
#                 GObject.idle_add(self.emit, "progress", -1, "Optimizing Energy ...")
#                 self.beamline.mostab.start()
#                 self.beamline.mostab.wait()
                   
            self.count = 0
            self.beamline.exposure_shutter.open()
            #_logger.info("%4s %15s %15s %15s %15s" % ('#', 'Energy', 'Scaled Counts', 'I_0','Unscaled Counts'))
            self.data_names = ['Energy',
                               'Scaled Counts',
                               'I_0',
                               'Raw Counts']
            GObject.idle_add(self.emit, 'progress', 0.0, "")
            
            for x in self._targets:
                if self._paused:
                    GObject.idle_add(self.emit, 'paused', True, self._notify)
                    self._notify = False
                    _logger.warning("Edge Scan paused at point %s." % str(x))
                    while self._paused and not self._stopped:
                        time.sleep(0.05)

                    self.beamline.goniometer.set_mode('SCANNING', wait=True)  
                    GObject.idle_add(self.emit, 'paused', False, False)
                    _logger.info("Scan resumed.")                
                if self._stopped:
                    _logger.info("Scan stopped!")
                    break
                    
                self.count += 1
                self.beamline.monochromator.simple_energy.move_to(x, wait=True)
                y, i0 = multi_count(self.beamline.mca, self.beamline.i_0, self._duration)
                if self.count == 1:
                    scale = 1.0
                else:
                    scale = (self.data[0][2]/i0)
                x = self.beamline.monochromator.simple_energy.get_position()
                self.data.append( [x, y*scale, i0, y] )
                    
                fraction = float(self.count) / len(self._targets)
                _logger.debug("%4d %15g %15g %15g %15g" % (self.count, x, y*scale, i0, y))
                GObject.idle_add(self.emit, "new-point", (x, y*scale, i0, y))
                GObject.idle_add(self.emit, "progress", fraction, "Doing Scan ...")
                             
            if self._stopped:
                if self.count < 2:
                    GObject.idle_add(self.emit, "stopped")
                    self.results = {'energies': None}
                    return
                _logger.warning("XANES Scan stopped. Will Attempt CHOOCH Analysis")
                self.save(self._filename)
                self.analyse()
                GObject.idle_add(self.emit, "stopped")
            else:
                _logger.info("XANES Scan complete. Analysing scan with CHOOCH.")
                self.save(self._filename)
                self.analyse()
                GObject.idle_add(self.emit, "done")
                GObject.idle_add(self.emit, "progress", 1.0, "Done")
        finally:
            self.beamline.monochromator.energy.move_to(self._edge_energy)
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.mca.configure(retract=False)
            _logger.info('Edge scan done.')
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.lock.release()           
        return self.results


class EXAFSScan(BasicScan):
    def __init__(self, edge='Se-K', t=1.0, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self._energy_db = get_energy_database()
        self.configure(edge, t, attenuation, directory, 'exafs')
        
    def configure(self, edge, t, attenuation, directory, prefix, scans=1, kmax=12, crystal=None, uname=None):
        #FIXME: Possible race condition here if new configure is issued while previous scan is still running
        # - maybe we should use queues and have the scan constantly check and perform a scan
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        try:
            self.beamline.storage_ring.disconnect(self.beam_connect)
        except:
            pass
        self.beam_connect = self.beamline.storage_ring.connect('beam', self.on_beam_change)
        self.scan_parameters = {}
        self.scan_parameters['edge'] = edge
        self.scan_parameters['edge_energy'],  self.scan_parameters['roi_energy'] = self._energy_db[edge]
        self.scan_parameters['duration'] = t
        self.scan_parameters['directory'] = directory
        self.scan_parameters['prefix'] = prefix
        self.scan_parameters['user_name'] = uname
        self.scan_parameters['targets'] = exafs_targets(self.scan_parameters['edge_energy'], kmax=kmax)
        self.scan_parameters['filename_template'] = os.path.join(directory, "%s_%s.raw" % (prefix, "%03d"))
        self.scan_parameters['attenuation'] = attenuation
        self.scan_parameters['crystal_id'] = crystal
        self.scan_parameters['no_scans'] = scans
        self.meta_data = {'edge': edge, 'time': t, 'attenuation': attenuation, 'scans': scans, 'kmax': kmax, 'prefix': prefix, 'user_name': uname}
        
                    
    def save(self, filename):
        """Save EXAFS output in XDI 1.0 format"""
        
        fmt_prefix = '%10'
        try:
            f = open(filename,'w')
        except:
            _logger.error("Could not open file '%s' for writing" % filename)
            return
        f.write('# XDI/1.0 MXDC\n')
        f.write('# Beamline.name: CLS %s\n' % self.beamline.name)
        f.write('# Beamline.edge-energy: %0.2f\n' % (1000.0 * self.scan_parameters['edge_energy']))
        f.write('# Beamline.d-spacing: %0.5f\n' % converter.energy_to_d(self.scan_parameters['edge_energy']))
        f.write('# Time.start: %s\n' % self.scan_parameters['start_time'].isoformat())
        f.write('# Time.end: %s\n' % self.scan_parameters['end_time'].isoformat())
        
        header = ''
        for i , info in enumerate(self.data_names):
            name, units, fmts = info
            fmt = fmt_prefix + 's '
            header += fmt % (name )
            f.write('# Column.%d: %s %s\n' % (i+1, name, units))

        f.write('#///\n')
        f.write('# %s, EXAFS\n' % (self.scan_parameters['edge']))
        f.write('# %s\n' % json.dumps(self.meta_data))
        f.write('# %d data points\n' % len(self._targets)) 
        f.write('#---\n')
        f.write('# %s\n' % header[2:])
        for point in self.data:
            for info, val in zip(self.data_names, point):
                name, units, fmts = info
                fmt = fmt_prefix + fmts + ' '
                f.write(fmt % val)
            f.write('\n')

        f.close()
        return filename
    
    def analyse(self):
        pass
        
    def run(self):
        self._paused = False
        _logger.info('EXAFS Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()

        # Obtain scan parameters from recent configure
        self._duration = self.scan_parameters['duration']
        self._edge = self.scan_parameters['edge']
        self._edge_energy = self.scan_parameters['edge_energy']
        self._roi_energy = self.scan_parameters['roi_energy']      
        self._targets = self.scan_parameters['targets']        
        self._attenuation = self.scan_parameters['attenuation']
        self._directory = self.scan_parameters['directory']
        self._prefix = self.scan_parameters['prefix']
        self._user_name = self.scan_parameters['user_name']
        self._crystal_id = self.scan_parameters['crystal_id']
        self.data = []
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            _logger.info('EXAFS scan started.')
            self.beamline.goniometer.set_mode('SCANNING')
            GObject.idle_add(self.emit, "progress", -1, "Preparing devices ...")
            self.beamline.attenuator.set(self._attenuation)
            self.beamline.multi_mca.configure(retract=True, cooling=True, energy=self._roi_energy)
            GObject.idle_add(self.emit, "progress", -1, "Moving to Mid-point ...")
            _cur_energy = self.beamline.energy.get_position()
            self.beamline.energy.move_to(self._edge_energy+0.2) # for exafs optimize a 0.2 above edge
            self.beamline.energy.wait()
            self.beamline.bragg_energy.wait()
            
#             # if energy just moved more than 10eV, optimize
#             if abs(_cur_energy - (self._edge_energy+0.2)) >= 0.01:
#                 GObject.idle_add(self.emit, "progress", -1, "Optimizing Energy ...")
#                 self.beamline.mostab.start()
#                 self.beamline.mostab.wait()
                    
            self.beamline.exposure_shutter.open()
            self.data_names = [  # last string in tuple is format suffix appended to end of '%n' 
                ('energy','eV', '.2f'),
                ('normfluor', '', '.8g'),
                ('i0', '', '.8g'),
                ('k', '', '.6f'),
                ('time','', '.4g'),
            ]
            for ch in range(self.beamline.multi_mca.elements):
                self.data_names.append(('ifluor.%d' % (ch+1), '', 'g'))
                self.data_names.append(('icr.%d' % (ch+1), '', 'g'))
                self.data_names.append(('ocr.%d' % (ch+1), '', 'g'))
                               
            # calculate k and time for each target point
            _tot_time = 0.0
            _k_time = []
            self.scan_parameters['start_time'] = datetime.now()
            for v in self._targets:
                _k = converter.energy_to_kspace(v - self._edge_energy)
                _t = science.exafs_time_func(self._duration, _k)
                _k_time.append((_k, _t))
                _tot_time += _t
            
            for _pass in range(self.scan_parameters['no_scans']):
                _used_time = 0.0
                self.count = 0
                GObject.idle_add(self.emit, 'started')
                GObject.idle_add(self.emit, "progress", 0.0 , "")
                for x, kt in zip(self._targets, _k_time):
                    if self._paused:
                        GObject.idle_add(self.emit, 'paused', True, self._notify)
                        self._notify = False
                        _logger.warning("EXAFS Scan paused at point %s." % str(x))
                        while self._paused and not self._stopped:
                            time.sleep(0.05)
                        if self._notify:
                            self.pause(True)
                            continue
                        self.beamline.goniometer.set_mode('SCANNING', wait=True)   
                        GObject.idle_add(self.emit, 'paused', False, self._notify)
                        _logger.info("Scan resumed.")
                    if self._stopped:
                        _logger.info("Scan stopped!")
                        break
                        
                    self.count += 1
                    self.beamline.monochromator.simple_energy.move_to(x, wait=True)
                    k, _t = kt
                    y,i0 = multi_count(self.beamline.multi_mca, self.beamline.i_0, _t)
                    mca_values = self.beamline.multi_mca.get_roi_counts()
                    if self.count == 1:
                        scale = 1.0
                    else:
                        scale = (self.data[0][2]/(i0*_t))
                        
                    x = self.beamline.monochromator.simple_energy.get_position()
                    data_point = [1000*x, y*scale, i0, k, _t] # convert KeV to eV
                    _corrected_sum = 0
                    _rates = self.beamline.multi_mca.get_count_rates()
                    for j in range(self.beamline.multi_mca.elements):
                        data_point.append(mca_values[j]) #iflour
                        data_point.append(_rates[j][0])  #icr
                        data_point.append(_rates[j][1])  #ocr
                        _corrected_sum +=  mca_values[j] * float(_rates[j][0])/_rates[j][1]
                    #data_point[1] = _corrected_sum * scale    
                    self.data.append(data_point)
                    
                    _used_time += _t    
                    fraction = _used_time / _tot_time
                    GObject.idle_add(self.emit, "new-point", (x, y*scale, i0, k,  y))
                    GObject.idle_add(self.emit, "progress", fraction , "Scan %d/%d" % (_pass+1, self.scan_parameters['no_scans']))
                                 
                self.scan_parameters['end_time'] = datetime.now()
                self._filename = self.scan_parameters['filename_template'] % (_pass+1)
                self.save(self._filename)
                self.data = []

                if self._stopped:
                    _logger.warning("EXAFS Scan stopped.")    
                    GObject.idle_add(self.emit, "stopped")
                    break
                else:
                    _msg = "Scan %d/%d complete." % (_pass+1, self.scan_parameters['no_scans'])
                    _logger.info(_msg)
                    GObject.idle_add(self.emit, "progress", 1.0, _msg)
            GObject.idle_add(self.emit, "done")
        finally:
            self.beamline.monochromator.energy.move_to(self._edge_energy)
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.multi_mca.configure(retract=False)
            _logger.info('EXAFS scan done.')
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.lock.release()        
        return self.data
    