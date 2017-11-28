"""This module defines classes aid interfaces for X-Ray fluorescence."""
import copy
import os
import time
from collections import OrderedDict
from datetime import datetime

from gi.repository import GObject
from twisted.python.components import globalRegistry

from mxdc.beamlines.interfaces import IBeamline
from mxdc.engines.chooch import AutoChooch
from mxdc.engines.scanning import BasicScan
from mxdc.utils import scitools, misc, datatools, xdi
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import multi_count
from mxdc.utils.scitools import *

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class XRFScanner(BasicScan):
    """
    X-Ray Fluorescence Spectroscopy (XRF) Scan. Sample is exposed at a fixed energy and the
    spectrum of all emission peaks for elements absorbing at or below the beam
    energy is acquired for a fixed amount of time.
    """
    def __init__(self):
        super(XRFScanner, self).__init__()
        
    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = copy.deepcopy(info)
        self.config['filename'] = os.path.join(info['directory'], "{}.xdi".format(info['name'], info['energy']))
        self.config['user'] = misc.get_project_name()
        self.results = {}
        self.units['energy'] = 'keV'
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

    def set_data(self, raw_data):
        self.data_types = {
            'names': ['energy', 'normfluor'],
            'formats': [float, float],
        }
        extra_names = ['ifluor.{}'.format(i+1) for i in range(self.beamline.mca.elements)]
        self.data_types['names'] += extra_names
        self.data_types['formats'] += [float]*len(extra_names)
        self.data = numpy.core.records.fromarrays(raw_data.transpose(), dtype=self.data_types)
        return self.data

    def run(self):
        logger.debug('Excitation Scan waiting for beamline to become available.')
        self.total = 4
        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            try:
                GObject.idle_add(self.emit, 'started')
                self.config['start_time'] = datetime.now()
                self.prepare_for_scan()
                self.notify_progress(1, "Acquiring spectrum ...")
                self.beamline.fast_shutter.open()
                raw_data = self.beamline.mca.acquire(t=self.config['exposure'])
                self.set_data(raw_data)
                self.beamline.fast_shutter.close()
                self.config['end_time'] = datetime.now()
                self.save(self.config['filename'])
                self.notify_progress(3, "Interpreting spectrum ...")
                self.analyse()
                self.save_metadata()
                GObject.idle_add(self.emit, "done")
            finally:
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def stop(self, error=''):
        pass

    def pause(self, reason=''):
        pass

    def analyse(self):
        x = self.data['energy'].astype(float)
        y = self.data['normfluor'].astype(float)
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

        # floats here
        ys = scitools.smooth_data(y, times=3, window=11)
        self.results = {
            'energy': x.tolist(),
            'counts': ys.tolist(),
            'fit': bblocks.sum(1).tolist(),
            'assignments': assigned
        }

        # save to file
        filename = os.path.join(self.config['directory'], '{}.xrf'.format(self.config['name']))
        with open(filename, 'w') as handle:
            json.dump(self.results, handle)
            logger.info("XRF Analysis Saved: {}".format(filename))

    def prepare_xdi(self):
        xdi_data = super(XRFScanner, self).prepare_xdi()
        xdi_data['Element.symbol'], xdi_data['Element.edge'] = self.config['edge'].split('-')
        xdi_data['Scan.edge_energy'] = self.config['energy'], 'keV'
        if 'sample' in self.config:
            xdi_data['Sample.name'] = self.config['sample'].get('name', 'unknown')
            xdi_data['Sample.id'] = self.config['sample'].get('sample_id', 'unknown')
            xdi_data['Sample.temperature'] = (self.beamline.cryojet.temperature, 'K')
            xdi_data['Sample.group'] = self.config['sample'].get('group', 'unknown')
        xdi_data['Scan.end_time'] = self.config['end_time']
        xdi_data['Scan.start_time'] = self.config['start_time']
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(
            self.config['energy'], self.beamline.config['mono_unit_cell']
        )
        return xdi_data

    def save_metadata(self, upload=True):
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
            'beam_size': self.beamline.aperture.get_position(),
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        if upload:
            self.beamline.lims.upload_data(self.beamline.name, filename)
        return metadata


class MADScanner(BasicScan):
    """
    Multi-Wavelength Anomalous Dispersion (MAD) Scan. Monochromator is scanned around a specific  absorption-edge
    in a stepwise manner and the total emission for the selected absorption-edge is recorded for a fixed amount of time.
    """
    def __init__(self):
        super(MADScanner, self).__init__()
        self.emissions = get_energy_database()
        self.autochooch = AutoChooch()

    def configure(self, info):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.config = copy.deepcopy(info)

        self.config['edge_energy'], self.config['roi_energy'] = self.emissions[info['edge']]
        self.config['filename'] = os.path.join(info['directory'], "{}.xdi".format(info['name']))
        self.config['targets'] = xanes_targets(self.config['edge_energy'])
        self.config['user'] = misc.get_project_name()
        self.results = {}
        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])
    
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
            self.data_rows = []
            self.results = {}
            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.beamline.fast_shutter.open()
                reference = 0.0
                self.config['start_time'] = datetime.now()
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
                        reference = i0
                    else:
                        scale = float(reference)/i0

                    self.data_rows.append((x, y*scale, y, i0))
                    GObject.idle_add(self.emit, "new-point", (x, y*scale, y, i0))
                    self.notify_progress(i+1, "Scanning {} of {} ...".format(i, self.total))
                    time.sleep(0)

                self.set_data(self.data_rows)
                self.config['end_time'] = datetime.now()
                self.save(self.config['filename'])
                if self.stopped:
                    logger.warning("Scan stopped.")
                    self.save_metadata()
                    GObject.idle_add(self.emit, "stopped")
                else:
                    logger.info("Scan complete. Performing Analyses")
                    self.analyse()
                    self.save_metadata()
                    GObject.idle_add(self.emit, "done")
            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def analyse(self):
        self.autochooch.configure(self.config, self.data)
        report = self.autochooch.run()
        if report:
            self.results['choices'] = report['choices']
            self.results['esf'] = {
                k: report['esf'][k].tolist() for k in report['esf'].dtype.names
            }
            # save to file
            filename = os.path.join(self.config['directory'], '{}.mad'.format(self.config['name']))
            with open(filename, 'w') as handle:
                json.dump(self.results, handle)
                logger.info("MAD Analysis Saved: {}".format(filename))

        else:
            GObject.idle_add(self.emit, 'error', 'Analysis Failed')

    def set_data(self, raw_data):
        self.data_types = {
            'names': ['energy', 'normfluor', 'ifluor', 'i0'],
            'formats': [float, float, float, float],
        }
        self.units = {
            'energy': 'keV'
        }
        self.data = numpy.array(raw_data, dtype=self.data_types)
        return self.data

    def prepare_xdi(self):
        xdi_data = super(MADScanner, self).prepare_xdi()
        xdi_data['Element.symbol'], xdi_data['Element.edge'] = self.config['edge'].split('-')
        xdi_data['Scan.edge_energy'] = self.config['edge_energy'], 'keV'
        if 'sample' in self.config:
            xdi_data['Sample.name'] = self.config['sample'].get('name', 'unknown')
            xdi_data['Sample.id'] = self.config['sample'].get('sample_id', 'unknown')
            xdi_data['Sample.temperature'] = (self.beamline.cryojet.temperature, 'K')
            xdi_data['Sample.group'] = self.config['sample'].get('group', 'unknown')
        xdi_data['Scan.end_time'] = self.config['end_time']
        xdi_data['Scan.start_time'] = self.config['start_time']
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(
            self.config['edge_energy'], self.beamline.config['mono_unit_cell']
        )
        return xdi_data

    def save_metadata(self, upload=True):
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
            'beam_size': self.beamline.aperture.get_position(),
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        if upload:
            self.beamline.lims.upload_data(self.beamline.name, filename)
        return metadata


class XASScanner(BasicScan):
    """
    X-Ray Absorption Spectroscopy (XAS, XANES, EXAFS). Monochromator is scanned around a specific  absorption-edge
    in a stepwise manner and the total emission for the selected absorption-edge is recorded.
    """
    __gsignals__ = {'new-scan' : (GObject.SignalFlags.RUN_FIRST, None, (int,)) }

    def __init__(self):
        super(XASScanner, self).__init__()
        self.emissions = get_energy_database()
        self.total_time = 0
        self.scan_index = 0

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
            self.data_rows = []
            self.results = {'data': [], 'scans': []}
            try:
                GObject.idle_add(self.emit, 'started')
                self.prepare_for_scan()
                self.beamline.fast_shutter.open()
                self.beamline.fast_shutter.open()

                # calculate k and time for each target point
                self.total_time = 0.0
                targets_times = []
                for i, v in enumerate(self.config['targets']):
                    k = converter.energy_to_kspace(v - self.config['edge_energy'])
                    t = scitools.exafs_time_func(self.config['exposure'], k)
                    targets_times.append((i, v, k, t))
                    self.total_time += t
                self.total_time *= self.config['scans']
                used_time = 0.0
                scan_length = len(self.config['targets'])
                reference = 1.0
                for scan in range(self.config['scans']):
                    self.config['start_time'] = datetime.now()
                    self.scan_index = scan + 1
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
                            reference = i0 * t
                        else:
                            scale = reference / (i0 * t)

                        data_point = [x, y * scale, i0, k, t]
                        corrected_sum = 0
                        rates = self.beamline.multi_mca.get_count_rates()
                        for j in range(self.beamline.multi_mca.elements):
                            data_point += [mca_values[j], rates[j][0], rates[j][1]]
                            corrected_sum += mca_values[j] * float(rates[j][0]) / rates[j][1]
                        data_point[1] = corrected_sum
                        self.data_rows.append(tuple(data_point))
                        used_time += t
                        GObject.idle_add(self.emit, "new-point", (x, y * scale, y, i0))
                        self.notify_progress(
                            used_time, "Scan {}/{}:  Point {}/{}...".format(
                                scan + 1, self.config['scans'], i, scan_length
                            )
                        )
                        time.sleep(0)
                    data = self.set_data(self.data_rows)
                    self.results['data'].append(data)
                    self.config['end_time'] = datetime.now()
                    filename = os.path.join(self.config['directory'], self.config['frame_template'].format(scan + 1))
                    self.save(filename)
                    self.analyse()
                    GObject.idle_add(self.emit, 'new-scan', scan + 1)
                    self.data_rows = []

                if self.stopped:
                    logger.warning("Scan stopped.")
                    GObject.idle_add(self.emit, "stopped")

                else:
                    logger.info("Scan complete.")
                    GObject.idle_add(self.emit, "done")
                self.save_metadata()

            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.multi_mca.configure(retract=False)
                logger.info('Edge scan done.')
                self.beamline.goniometer.set_mode('COLLECT')
        return self.results

    def set_data(self, raw_data):
        self.data_types = {
            'names': ['energy', 'normfluor', 'i0', 'k', 'exposure'],
            'formats': [float, float, float, float, float],
        }
        self.units = {
            'energy': 'keV',
            'exposure': 'seconds'
        }
        extra_names = []
        for ch in range(self.beamline.multi_mca.elements):
            extra_names.extend(['ifluor.{}'.format(ch + 1), 'icr.{}'.format(ch + 1), 'ocr.{}'.format(ch + 1)])
        self.data_types['names'] += extra_names
        self.data_types['formats'] += [float] * len(extra_names)
        self.data = numpy.array(raw_data, dtype=self.data_types)
        return self.data

    def analyse(self):
        x = self.data['energy']
        y = self.data['normfluor']
        y_peak = y.max()
        x_peak = x[y==y_peak][0]
        self.results['scans'].append({
            'scan': self.scan_index,
            'name': self.config['name'],
            'edge': self.config['edge'],
            'directory': self.config['directory'],
            'x_peak': x_peak,
            'y_peak': y_peak,
            'time': datetime.now().strftime('%H:%M:%S')
        })

    def prepare_xdi(self):
        xdi_data = super(XASScanner, self).prepare_xdi()
        xdi_data['Element.symbol'],  xdi_data['Element.edge']= self.config['edge'].split('-')
        xdi_data['Scan.edge_energy'] = self.config['edge_energy'], 'keV'
        if 'sample' in self.config:
            xdi_data['Sample.name'] = self.config['sample'].get('name', 'unknown')
            xdi_data['Sample.id'] = self.config['sample'].get('sample_id', 'unknown')
            xdi_data['Sample.temperature'] = (self.beamline.cryojet.temperature, 'K')
            xdi_data['Sample.group'] = self.config['sample'].get('group', 'unknown')
        xdi_data['Scan.end_time'] = self.config['end_time']
        xdi_data['Scan.start_time'] = self.config['start_time']
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(self.config['edge_energy'], self.beamline.config['mono_unit_cell'])
        xdi_data['Scan.series'] = '{} of {}'.format(self.scan_index, self.config['scans'])
        return xdi_data

    def save_metadata(self, upload=True):

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
                'beam_size': self.beamline.aperture.get_position(),
            }
            filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
            logger.debug('Saving meta-data: {}'.format(filename))
            misc.save_metadata(metadata, filename)

            if upload:
                self.beamline.lims.upload_data(self.beamline.name, filename)
            return metadata