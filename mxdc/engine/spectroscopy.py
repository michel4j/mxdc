"""This module defines classes aid interfaces for X-Ray fluorescence."""
from mxdc.interface.beamlines import IBeamline
from mxdc.engine.chooch import AutoChooch
from mxdc.engine.scanning import BasicScan, ScanError
from mxdc.service.utils import  send_array
from mxdc.utils import scitools, json, converter, misc, datatools
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_short_uuid, multi_count
from mxdc.utils.scitools import *
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
        self.config = copy.deepcopy(info)
        self.config['filename'] = os.path.join(info['directory'], "{}.xdi".format(info['name'], info['energy']))
        #self.config['results_file'] = os.path.join(info['directory'], "{}.out".format(info['name'], info['energy']))
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
                self.save_metadata()
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
        sel = (x < 0.5) | (x > energy - self.beamline.config.get('xrf_energy_offset', 2.0))
        y[sel] = 0.0

        # set FWHM of detector
        scitools.PEAK_FWHM = self.beamline.config.get('xrf_fwhm', 0.1)
        elements, bblocks, coeffs = scitools.interprete_xrf(x, y, energy)
        assigned = {}
        for i, el_info in enumerate(elements):
            symbol = el_info[0]
            if coeffs[i] > 0.001:
                prob = 100.0 * bblocks[:, i].sum() / y.sum()
                if prob > 0.1:
                    line_info = scitools.get_line_info(el_info, coeffs[i])
                    if line_info is not None:
                        assigned[symbol] = [prob, scitools.get_line_info(el_info, coeffs[i])]

                        # twisted does not like numpy.float64 so we need to convert x, y to native python
        # floats here
        ys = scitools.smooth_data(y, times=3, window=11)
        self.results = {
            'data': {
                'energy': x.tolist(),
                'counts': y.tolist(),


            },
            'analysis': {
                'energy': x.tolist(),
                'counts': ys.tolist(),
                'fit': bblocks.sum(1).tolist(),
                'assignments': assigned
            },
        }
        #with open(self.config['results_file'], 'w') as handle:
        #    json.dump(self.results, handle)

    def save_metadata(self):
        params = self.config
        metadata = {
            'name': params['name'],
            'frames':  "",
            'filename': os.path.basename(params['filename']),
            'container': params['container'],
            'port': params['port'],
            'type': 'XRF_SCAN',
            'sample_id': params['sample_id'],
            'uuid': params['uuid'],
            'directory': params['directory'],

            'energy': params['energy'],
            'attenuation': params['attenuation'],
            'exposure': params['exposure'],
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        if os.path.exists(filename):
            with open(filename, 'r') as handle:
                old_meta = json.load(handle)
                metadata['id'] = old_meta.get('id')

        with open(filename, 'w') as handle:
            json.dump(metadata, handle, indent=2, separators=(',',':'), sort_keys=True)
            logger.info("Meta-Data Saved: {}".format(filename))

        return metadata


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
        self.data = []

    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = copy.deepcopy(info)

        self.config['edge_energy'], self.config['roi_energy'] = self._energy_db[info['edge']]
        self.config['filename'] = os.path.join(info['directory'], "{}_{}.xdi".format(info['name'], info['edge']))
        self.config['targets'] = xanes_targets(self.config['edge_energy'])
        self.config['user'] = misc.get_project_name()
        self.results = {}
        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])
    
    def analyse(self):
        self.autochooch.configure(self.config, numpy.array(self.data))
        report = self.autochooch.run()
        if report:
            self.results['analysis'] = report
        else:
            GObject.idle_add(self.emit, 'error', 'Analysis Failed')

    def notify_progress(self, pos, message):
        fraction = float(pos) / self.total
        GObject.idle_add(self.emit, "progress", fraction, message)

    def prepare_for_scan(self):
        self.notify_progress(0.01, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['edge_energy'])
        self.beamline.goniometer.set_mode('SCANNING')
        self.beamline.mca.configure(retract=True, cooling=True, energy=self.config['roi_energy'], edge=self.config['edge_energy'])
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.bragg_energy.wait()
        self.beamline.goniometer.wait(start=False)
        self.notify_progress(0.02, "Waiting for beam to stabilize ...")
        time.sleep(3)

    def run(self):
        logger.info('Edge Scan waiting for beamline to become available.')

        with self.beamline.lock:
            self.total = len(self.config['targets'])
            saved_attenuation = self.beamline.attenuator.get()
            self.data = []
            self.results = {'data': [], 'analysis': {}}
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
                    time.sleep(0)

                if len(self.data) > 10:
                    data = numpy.array(self.data)
                    self.results['data'] = {
                        'energy': data[:, 0].astype(float),
                        'counts': data[:, 1].astype(float),
                        'I0': data[:, 2].astype(float),
                        'raw_counts': data[:, 3].astype(float),
                    }

                if self.stopped:
                    logger.warning("Scan stopped.")
                    self.save(self.config['filename'])
                    self.save_metadata()
                    GObject.idle_add(self.emit, "stopped")
                else:
                    logger.info("Scan complete. Performing Analyses")
                    self.save(self.config['filename'])
                    self.analyse()
                    self.save_metadata()
                    GObject.idle_add(self.emit, "done")
            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.exposure_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def save_metadata(self):
        params = self.config
        metadata = {
            'name': params['name'],
            'frames':  "",
            'filename': os.path.basename(params['filename']),
            'container': params['container'],
            'port': params['port'],
            'type': 'MAD_SCAN',
            'sample_id': params['sample_id'],
            'uuid': params['uuid'],
            'directory': params['directory'],

            'energy': params['edge_energy'],
            'attenuation': params['attenuation'],
            'exposure': params['exposure'],
            'edge': params['edge'],
            'roi': self.beamline.mca.get_roi(params['roi_energy']),
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        if os.path.exists(filename):
            with open(filename, 'r') as handle:
                old_meta = json.load(handle)
                metadata['id'] = old_meta.get('id')

        with open(filename, 'w') as handle:
            json.dump(metadata, handle, indent=2, separators=(',',':'), sort_keys=True)
            logger.info("Meta-Data Saved: {}".format(filename))

        return metadata


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
        self.config = copy.deepcopy(info)
        self.config['edge_energy'], self.config['roi_energy'] = self.emissions[info['edge']]
        self.config['frame_template'] = '{}-{}_{}.xdi'.format(info['name'], info['edge'], '{:0>3d}')
        self.config['frame_glob']     = '{}-{}_{}.xdi'.format(info['name'], info['edge'], '*')
        self.config['targets'] = exafs_targets(self.config['edge_energy'], kmax=info['kmax'])
        self.config['user'] = misc.get_project_name()
        self.results = {}

        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def notify_progress(self, used_time, message):
        fraction = float(used_time) / max(abs(self.total_time), 1)
        GObject.idle_add(self.emit, "progress", fraction, message)

    def prepare_for_scan(self):
        self.notify_progress(0.001, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['edge_energy'])
        self.beamline.goniometer.set_mode('SCANNING')
        self.beamline.multi_mca.configure(retract=True, cooling=True, energy=self.config['roi_energy'], edge=self.config['edge_energy'])
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.bragg_energy.wait()
        self.beamline.goniometer.wait(start=False)
        self.notify_progress(0.002, "Waiting for beam to stabilize ...")
        time.sleep(3)

    def run(self):
        logger.info('Scan waiting for beamline to become available.')

        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            self.data = []
            self.results = {'data': [], 'scans': []}

            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.beamline.exposure_shutter.open()
                self.beamline.exposure_shutter.open()
                self.data_names = [  # last string in tuple is format suffix appended to end of '%n'
                    ('energy', 'keV', '.4f'),
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
                    t = scitools.exafs_time_func(self.config['exposure'], k)
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

                        #x = self.beamline.bragg_energy.get_position()
                        data_point = [x, y * scale, i0, k, t]  # convert KeV to eV
                        corrected_sum = 0
                        rates = self.beamline.multi_mca.get_count_rates()
                        for j in range(self.beamline.multi_mca.elements):
                            data_point.append(mca_values[j])  # iflour
                            data_point.append(rates[j][0])  # icr
                            data_point.append(rates[j][1])  # ocr
                            corrected_sum += mca_values[j] * float(rates[j][0]) / rates[j][1]
                        data_point[1] = corrected_sum
                        self.data.append(data_point)
                        used_time += t
                        GObject.idle_add(self.emit, "new-point", (x, y * scale, i0, y))
                        self.notify_progress(
                            used_time, "Scan {}/{}:  Point {}/{}...".format(
                                scan + 1, self.config['scans'], i, scan_length
                            )
                        )
                        time.sleep(0)

                    self.config['end_time'] = datetime.now()
                    filename = self.config['frame_template'].format(scan + 1)
                    self.save(filename)
                    self.results['data'].append(numpy.array(self.data))
                    self.analyse()
                    GObject.idle_add(self.emit, 'new-scan', scan + 1)
                    self.data = []

                if self.stopped:
                    logger.warning("Scan stopped.")
                    self.save_metadata()
                    GObject.idle_add(self.emit, "stopped")

                else:
                    logger.info("Scan complete.")
                    self.save_metadata()
                    GObject.idle_add(self.emit, "done")

            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.exposure_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.multi_mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def analyse(self):
        data = self.results['data'][-1]
        x = data[:,0]
        y = data[:,1]
        y_peak = y.max()
        x_peak = x[y==y_peak][0]
        self.results['scans'].append({
            'scan': len(self.results['data']),
            'name': self.config['name'],
            'edge': self.config['edge'],
            'directory': self.config['directory'],
            'x_peak': x_peak,
            'y_peak': y_peak,
            'time': datetime.now().strftime('%H:%M:%S')
        })

    def save_metadata(self):
        params = self.config
        frames, count = datatools.get_disk_frameset(params['directory'], params['frame_glob'])
        if count:
            metadata = {
                'name': params['name'],
                'frames':  frames,
                'filename': params['frame_template'],
                'container': params['container'],
                'port': params['port'],
                'type': 'XAS_SCAN',
                'sample_id': params['sample_id'],
                'uuid': params['uuid'],
                'directory': params['directory'],

                'energy': params['edge_energy'],
                'attenuation': params['attenuation'],
                'exposure': params['exposure'],
                'edge': params['edge'],
                'roi': self.beamline.mca.get_roi(params['roi_energy']),
                'kmax': params['kmax'],
            }
            filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
            if os.path.exists(filename):
                with open(filename, 'r') as handle:
                    old_meta = json.load(handle)
                    metadata['id'] = old_meta.get('id')

            with open(filename, 'w') as handle:
                json.dump(metadata, handle, indent=2, separators=(',',':'), sort_keys=True)
                logger.info("Meta-Data Saved: {}".format(filename))

            return metadata

    def save(self, filename=None):
        """Save EXAFS output in XDI 1.0 format"""
        fmt_prefix = '%10'
        with open(os.path.join(self.config['directory'], filename), 'w') as handle:
            handle.write('# XDI/1.0 MXDC\n')
            handle.write('# Beamline.name: CLS %s\n' % self.beamline.name)
            handle.write('# Beamline.edge-energy: %0.2f\n' % (self.config['edge_energy']))
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
            logger.info('Scan saved: {}'.format(filename))
        return filename