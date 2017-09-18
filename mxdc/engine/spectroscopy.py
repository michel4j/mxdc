"""This module defines classes aid interfaces for X-Ray fluorescence."""
from mxdc.interface.beamlines import IBeamline
from mxdc.engine.autochooch import AutoChooch
from mxdc.engine.scanning import BasicScan, ScanError
from mxdc.service.utils import  send_array
from mxdc.utils import science, json, converter, misc
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_short_uuid, multi_count
from mxdc.utils.science import *
from datetime import datetime
from twisted.python.components import globalRegistry
from zope.interface import Interface, Attribute, invariant
from gi.repository import GObject
import copy
import os
import re
import time


# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

class XRFScanner(BasicScan):
    def __init__(self):
        BasicScan.__init__(self)
        self.data_names = ['Energy', 'Counts']
        self.beamline = None
        self.paused = False
        self.stopped = False
        self.total = 0
        self.config = {}
        self.results = {}
        
    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = {}
        self.config['name'] = info['name']
        self.config['energy'] = info['energy']
        self.config['exposure'] = info['exposure']
        self.config['directory'] = info['directory']
        self.config['filename'] = os.path.join(info['directory'], "{}_{:0.3f}.raw".format(info['name'], info['energy']))
        self.config['results_file'] = os.path.join(info['directory'], "{}_{:0.3f}.out".format(info['name'], info['energy']))
        self.config['attenuation'] = info['attenuation']
        self.config['sample_id'] = info.get('sample_id')
        self.config['activity'] = info['activity']
        self.config['user'] = misc.get_project_name()
        self.results = {}

        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def notify_progress(self, pos, message):
        fraction = float(pos)/self.total
        GObject.idle_add(self.emit, "progress", fraction, message)

    def prepare_for_scan(self):
        self.notify_progress(0.01, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['energy'])
        self.beamline.goniometer.set_mode('SCANNING')
        self.beamline.mca.configure(retract=True, cooling=True, energy=None)
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.goniometer.wait(start=False)

    def run(self):
        logger.debug('Excitation Scan waiting for beamline to become available.')
        self.total = 4
        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.data = []
                self.notify_progress(1, "Acquiring spectrum ...")
                self.beamline.exposure_shutter.open()
                self.data = self.beamline.mca.acquire(t=self.config['exposure'])
                self.beamline.exposure_shutter.close()
                self.save(self.config['filename'])
                self.notify_progress(3, "Interpreting spectrum ...")
                self.analyse()
                GObject.idle_add(self.emit, "done")
            finally:
                self.beamline.exposure_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def stop(self, error=''):
        pass

    def pause(self, reason):
        pass

    def analyse(self):
        x = self.data[:, 0].astype(float)
        y = self.data[:, 1].astype(float)
        energy = self.config['energy']
        sel = (x < 0.5) | (x > energy - 0.5 * self.beamline.config.get('xrf_energy_offset', 2.0))
        y[sel] = 0.0

        # set FWHM of detector
        science.PEAK_FWHM = self.beamline.config.get('xrf_fwhm', 0.1)
        elements, bblocks, coeffs = science.interprete_xrf(x, y, energy)
        assigned = {}
        for i, el_info in enumerate(elements):
            symbol = el_info[0]
            if coeffs[i] > 0.001:
                prob = 100.0 * bblocks[:, i].sum() / y.sum()
                if prob > 0.1:
                    line_info = science.get_line_info(el_info, coeffs[i])
                    if line_info is not None:
                        assigned[symbol] = [prob, science.get_line_info(el_info, coeffs[i])]

                        # twisted does not like numpy.float64 so we need to convert x, y to native python
        # floats here
        ys = science.smooth_data(y, times=3, window=11)
        self.results = {
            'data': {
                'energy': map(float, list(x)),
                'raw': map(float, list(self.data[:, 1])),
                'counts': map(float, list(ys)),
                'fit': map(float, list(bblocks.sum(1)))
            },
            'assigned': assigned,
            'parameters': {
                'directory': self.config['directory'],
                'energy': self.config['energy'],
                'exposure': self.config['exposure'],
                'output_file': self.config['filename'],
                'attenuation': self.config['attenuation'],
                'sample_id': self.config['sample_id'],
                'name': self.config['name']
            },
            'kind': self.config['activity'],  # Excitation Scan
        }
        with open(self.config['results_file'], 'w') as handle:
            json.dump(self.results, handle)


class MADScanner(BasicScan):
    def __init__(self):
        BasicScan.__init__(self)
        self._energy_db = get_energy_database()
        self.autochooch = AutoChooch()
        self.beamline = None
        self.paused = False
        self.stopped = False
        self.total = 0
        self.config = {}
        self.results = {}

    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = {}

        self.config['name'] = info['name']
        self.config['edge'] = info['edge']
        self.config['edge_energy'], self.config['roi_energy'] = self._energy_db[info['edge']]
        self.config['exposure'] = info['exposure']
        self.config['directory'] = info['directory']
        self.config['filename'] = os.path.join(info['directory'], "{}_{}.raw".format(info['name'], info['edge']))
        self.config['attenuation'] = info['attenuation']
        self.config['sample_id'] = info.get('sample_id')
        self.config['activity'] = info['activity']
        self.config['targets'] = xanes_targets(self.config['edge_energy'])
        self.config['user'] = misc.get_project_name()
        self.results = {}
        self.chooch_results = {}

        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def analyse_file(self, filename):
        data = numpy.loadtxt(filename)
        with open(filename, 'r') as handle:
            raw_text = handle.read()
        self.data = zip(data[:,0], data[:,1], data[:,2], data[:,3])
        
        meta = re.search('# Meta Data: ({.+})', raw_text)
        if meta:
            self.config = json.loads(meta.group(1))

        self.analyse()
        GObject.idle_add(self.emit, "done")
    
    def analyse(self):
        self.autochooch.configure(self.config['edge'], self.config['directory'], self.config['name'])
        success = self.autochooch.run()
        res_data = {
            'energy': [float(v[0]) for v in self.data],
            'counts': [float(v[1]) for v in self.data]
        }
        if success:
            _efs = self.autochooch.data
            efs_data = {
                'energy': map(float, _efs[:,0]),
                'fp': map(float, _efs[:,2]),
                'fpp': map(float, _efs[:,1])
            }
            self.results = {
                'data': res_data,
                'efs': efs_data,
                'energies': self.autochooch.results,
                'text': self.autochooch.results_text,
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self.config['name'], self.config['edge']),
                'directory': self.config['directory'],
                'edge': self.config['edge'],
                'sample_id': self.config['sample_id'],
                'attenuation': self.config['attenuation'],
                'energy': self.config['edge_energy'],
                'kind': self.config['activity'],  # Excitation Scan
            }
        else:
            GObject.idle_add(self.emit, 'error', 'Analysis Failed')
            self.results = {
                'data': res_data,
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self.config['name'], self.config['edge']),
                'directory': self.config['directory']
            }

    def notify_progress(self, pos, message):
        fraction = float(pos) / self.total
        GObject.idle_add(self.emit, "progress", fraction, message)

    def prepare_for_scan(self):
        self.notify_progress(0.01, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['edge_energy'])
        self.beamline.goniometer.set_mode('SCANNING')
        self.beamline.mca.configure(retract=True, cooling=True, energy=self.config['roi_energy'])
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.bragg_energy.wait()
        self.beamline.goniometer.wait(start=False)
        self.notify_progress(0.02, "Waiting for beam to stabilize ...")
        time.sleep(5)

    def run(self):
        logger.info('Edge Scan waiting for beamline to become available.')

        with self.beamline.lock:
            self.total = len(self.config['targets'])
            saved_attenuation = self.beamline.attenuator.get()
            self.chooch_results = {}

            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.beamline.exposure_shutter.open()
                self.data_names = ['Energy', 'Scaled Counts','I_0', 'Raw Counts']

                for i, x in enumerate(self.config['targets']):
                    if self.paused:
                        GObject.idle_add(self.emit, 'paused', True, '')
                        logger.warning("Edge Scan paused at point %s." % str(x))
                        while self.paused and not self.stopped:
                            time.sleep(0.05)

                        self.beamline.goniometer.set_mode('SCANNING', wait=True)
                        GObject.idle_add(self.emit, 'paused', False, '')
                        logger.info("Scan resumed.")
                    if self.stopped:
                        logger.info("Scan stopped!")
                        break

                    self.beamline.bragg_energy.move_to(x, wait=True)
                    y, i0 = multi_count(self.beamline.mca, self.beamline.i_0, self.config['exposure'])
                    if i == 0:
                        scale = 1.0
                    else:
                        scale = (self.data[0][2]/i0)
                    #x = self.beamline.bragg_energy.get_position()
                    self.data.append( [x, y*scale, i0, y] )
                    GObject.idle_add(self.emit, "new-point", (x, y*scale, i0, y))
                    self.notify_progress(i+1, "Scanning {} of {} ...".format(i, self.total))

                if self.stopped:
                    if len(self.data) < 2:
                        GObject.idle_add(self.emit, "stopped")
                        self.results = {'energies': None}
                        return
                    logger.warning("Scan stopped. Will Attempt Analysis")
                    self.save(self.config['filename'])
                    self.analyse()
                    GObject.idle_add(self.emit, "stopped")
                else:
                    logger.info("Scan complete. Performing Analyses")
                    self.save(self.config['filename'])
                    self.analyse()
                    GObject.idle_add(self.emit, "done")
            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.exposure_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results


class XASScanner(BasicScan):
    __gsignals__ = {'new-scan' : (GObject.SignalFlags.RUN_LAST, None, (int,)) }

    def __init__(self):
        BasicScan.__init__(self)
        self.emissions = get_energy_database()
        self.beamline = None
        self.paused = False
        self.stopped = False
        self.total_time = 0
        self.config = {}
        self.results = {}
        
    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = {}

        self.config['name'] = info['name']
        self.config['edge'] = info['edge']
        self.config['edge_energy'], self.config['roi_energy'] = self.emissions[info['edge']]
        self.config['exposure'] = info['exposure']
        self.config['directory'] = info['directory']
        self.config['filename_template'] = os.path.join(
            info['directory'], "{}_{}_{}.raw".format(info['name'], info['edge'], '{:0>3d}')
        )
        self.config['attenuation'] = info['attenuation']
        self.config['sample_id'] = info.get('sample_id')
        self.config['activity'] = info['activity']
        self.config['scans'] = info['scans']
        self.config['targets'] = exafs_targets(self.config['edge_energy'], kmax=info['kmax'])
        self.config['user'] = misc.get_project_name()
        self.results = {}

        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def analyse(self):
        pass

    def notify_progress(self, used_time, message):
        fraction = float(used_time) / max(abs(self.total_time), 1)
        GObject.idle_add(self.emit, "progress", fraction, message)

    def prepare_for_scan(self):
        self.notify_progress(0.001, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['edge_energy'])
        self.beamline.goniometer.set_mode('SCANNING')
        self.beamline.mca.configure(retract=True, cooling=True, energy=self.config['roi_energy'])
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.bragg_energy.wait()
        self.beamline.goniometer.wait(start=False)
        self.notify_progress(0.002, "Waiting for beam to stabilize ...")
        time.sleep(5)

    def run(self):
        logger.info('Scan waiting for beamline to become available.')

        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            self.data = []
            self.results = {
                'x': self.config['targets'],
                'y': []
            }

            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.beamline.exposure_shutter.open()
                self.beamline.exposure_shutter.open()
                self.data_names = [  # last string in tuple is format suffix appended to end of '%n'
                    ('energy', 'eV', '.2f'),
                    ('normfluor', '', '.8g'),
                    ('i0', '', '.8g'),
                    ('k', '', '.6f'),
                    ('time', '', '.4g'),
                ]
                for ch in range(self.beamline.multi_mca.elements):
                    self.data_names.append(('ifluor.%d' % (ch + 1), '', 'g'))
                    self.data_names.append(('icr.%d' % (ch + 1), '', 'g'))
                    self.data_names.append(('ocr.%d' % (ch + 1), '', 'g'))

                # calculate k and time for each target point
                self.total_time = 0.0
                targets_times = []
                self.config['start_time'] = datetime.now()
                for i, v in enumerate(self.config['targets']):
                    k = converter.energy_to_kspace(v - self.config['edge_energy'])
                    t = science.exafs_time_func(self.config['exposure'], k)
                    targets_times.append((i, v, k, t))
                    self.total_time += t
                self.total_time *= self.config['scans']
                used_time = 0.0
                scan_length = len(self.config['targets'])
                for scan in range(self.config['scans']):
                    for i, x, k, t in targets_times:
                        if self.paused:
                            GObject.idle_add(self.emit, 'paused', True, '')
                            logger.warning("Edge Scan paused at point %s." % str(x))
                            while self.paused and not self.stopped:
                                time.sleep(0.05)

                            self.beamline.goniometer.set_mode('SCANNING', wait=True)
                            GObject.idle_add(self.emit, 'paused', False, '')
                            logger.info("Scan resumed.")
                        if self.stopped:
                            logger.info("Scan stopped!")
                            break

                        self.beamline.bragg_energy.move_to(x, wait=True)
                        y, i0 = multi_count(self.beamline.multi_mca, self.beamline.i_0, t)
                        mca_values = self.beamline.multi_mca.get_roi_counts()
                        if i == 0:
                            scale = 1.0
                        else:
                            scale = (self.data[0][2] / (i0 * t))

                        x = self.beamline.bragg_energy.get_position()
                        data_point = [1000 * x, y * scale, i0, k, t]  # convert KeV to eV
                        corrected_sum = 0
                        rates = self.beamline.multi_mca.get_count_rates()
                        for j in range(self.beamline.multi_mca.elements):
                            data_point.append(mca_values[j])  # iflour
                            data_point.append(rates[j][0])  # icr
                            data_point.append(rates[j][1])  # ocr
                            corrected_sum += mca_values[j] * float(rates[j][0]) / rates[j][1]
                        # data_point[1] = _corrected_sum * scale
                        self.data.append(data_point)
                        self.results['y'].append(corrected_sum)
                        used_time += t
                        if i == 0:
                            GObject.idle_add(self.emit, 'new-scan', scan)
                        GObject.idle_add(self.emit, "new-point", (x, y * scale, i0, y))
                        self.notify_progress(
                            used_time, "Scan {}/{}:  Point {}/{}...".format(
                                scan, self.config['scans'], i, scan_length
                            )
                        )

                    self.config['end_time'] = datetime.now()
                    filename = self.config['filename_template'].format(scan + 1)
                    self.save(filename)
                    self.data = []

                if self.stopped:
                    logger.warning("Scan stopped.")
                    GObject.idle_add(self.emit, "stopped")
                else:
                    logger.info("Scan complete.")
                    GObject.idle_add(self.emit, "done")

            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.exposure_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def save(self, filename=None):
        """Save EXAFS output in XDI 1.0 format"""
        fmt_prefix = '%10'
        with open(filename, 'w') as handle:

            handle.write('# XDI/1.0 MXDC\n')
            handle.write('# Beamline.name: CLS %s\n' % self.beamline.name)
            handle.write('# Beamline.edge-energy: %0.2f\n' % (1000.0 * self.config['edge_energy']))
            handle.write('# Beamline.d-spacing: %0.5f\n' % converter.energy_to_d(self.config['edge_energy']))
            handle.write('# Time.start: %s\n' % self.config['start_time'].isoformat())
            handle.write('# Time.end: %s\n' % self.config['end_time'].isoformat())

            header = ''
            for i, info in enumerate(self.data_names):
                name, units, fmts = info
                fmt = fmt_prefix + 's '
                header += fmt % (name)
                handle.write('# Column.%d: %s %s\n' % (i + 1, name, units))
            meta_data = copy.deepcopy(self.config)
            meta_data.pop('targets')
            handle.write('#///\n')
            handle.write('# %s, EXAFS\n' % (self.config['edge']))
            #handle.write('# %s\n' % json.dumps(self.config))
            handle.write('# %d data points\n' % len(self.config['targets']))
            handle.write('#---\n')
            handle.write('# %s\n' % header[2:])
            for point in self.data:
                for info, val in zip(self.data_names, point):
                    name, units, fmts = info
                    fmt = fmt_prefix + fmts + ' '
                    handle.write(fmt % val)
                handle.write('\n')

        return filename