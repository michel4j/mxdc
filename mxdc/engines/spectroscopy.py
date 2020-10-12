"""This module defines classes aid interfaces for X-Ray fluorescence."""
import copy
import time
import os
import numpy
import json
from datetime import datetime

import pytz

from mxdc.engines.chooch import AutoChooch
from mxdc.engines.scanning import BasicScan
from mxdc.utils import converter
from mxdc.utils import scitools, misc, datatools
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import multi_count


# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class XRFScan(BasicScan):
    """
    X-Ray Fluorescence Spectroscopy (XRF) Scan. Sample is exposed at a fixed energy and the
    spectrum of all _emission peaks for elements absorbing at or below the beam
    energy is acquired for a fixed amount of time.
    """

    def configure(self, **kwargs):
        super().configure(**kwargs)
        self.config.update(
            filename=os.path.join(self.config.directory, "{}.xdi".format(self.config.name)),
            user=misc.get_project_name(),
        )

        self.data_units['energy'] = 'keV'
        names = ['energy', 'normfluor'] + ['ifluor{}'.format(i + 1) for i in range(self.beamline.mca.elements)]
        self.data_type = {
            'names': names,
            'formats': ['f4'] * len(names),
        }
        self.data_scale = [(names[1],)]
        self.results = {}

        # create directory
        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def scan(self):
        logger.debug('Excitation Scan waiting for beamline to become available.')
        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            try:
                self.emit("progress", 0.01, "Preparing devices ...")
                self.beamline.energy.move_to(self.config['energy'])
                self.beamline.manager.collect(wait=True)
                self.beamline.mca.configure(cooling=True, energy=None, nozzle=True)
                self.beamline.attenuator.set(self.config['attenuation'])
                time.sleep(2)
                self.beamline.energy.wait()
                self.beamline.goniometer.wait(start=False)
                self.emit("progress", .1, "Acquiring spectrum ...")
                self.beamline.fast_shutter.open()
                self.raw_data = self.beamline.mca.acquire(self.config.exposure)
                self.beamline.fast_shutter.close()
                self.config['end_time'] = datetime.now(tz=pytz.utc)
                self.emit("progress", 1, "Interpreting spectrum ...")
            finally:
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(cooling=False, nozzle=False)
                self.beamline.manager.collect()

    def finalize(self):
        self.data = numpy.core.records.fromarrays(self.raw_data.transpose(), dtype=self.data_type)
        self.save(self.config['filename'])
        self.analyse()
        self.save_metadata()

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
        xdi_data = super().prepare_xdi()
        xdi_data['Element.symbol'], xdi_data['Element.edge'] = self.config['edge'].split('-')
        xdi_data['Scan.edge_energy'] = self.config.energy, 'keV'
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(
            self.config['energy'], self.beamline.config['mono_unit_cell']
        )
        return xdi_data

    def save_metadata(self, upload=True):
        params = self.config
        metadata = {
            'name': params['name'],
            'frames': "",
            'filename': os.path.basename(params['filename']),
            'container': params['container'],
            'port': params['port'],
            'type': 'XRF',
            'start_time': params['start_time'].isoformat(),
            'end_time': params['end_time'].isoformat(),
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


class MADScan(BasicScan):
    """
    Multi-Wavelength Anomalous Dispersion (MAD) Scan. Monochromator is scanned around a specific  absorption-edge
    in a stepwise manner and the total _emission for the selected absorption-edge is recorded for a fixed amount of time.
    """

    def __init__(self):
        super().__init__()
        self.emissions = scitools.get_energy_database()
        self.chooch = AutoChooch()
        self.results = {}

    def configure(self, **kwargs):
        super().configure(**kwargs)
        edge_energy, roi_energy = self.emissions[self.config.edge]
        self.config.update(
            edge_energy=edge_energy,
            roi_energy=roi_energy,
            positions=scitools.xanes_targets(edge_energy),
            user=misc.get_project_name(),
            filename=os.path.join(self.config.directory, "{}.xdi".format(self.config.name))
        )
        names = ['energy', 'normfluor'] + ['ifluor{}'.format(i + 1) for i in range(self.beamline.mca.elements)] + ['i0']
        self.data_units['energy'] = 'keV'
        self.data_type = {
            'names': names,
            'formats': ['f4'] * len(names),
        }

        self.data_scale = [tuple(names[1:-1]), (names[-1],)]

        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def scan(self):
        logger.info('Edge Scan waiting for beamline to become available.')
        with self.beamline.lock:

            saved_attenuation = self.beamline.attenuator.get()
            self.raw_data = []
            self.results = {}

            ref_value = 1.0
            try:
                # prepare
                self.emit("progress", 0.01, "Preparing devices ...")
                self.beamline.energy.move_to(self.config.edge_energy)
                self.beamline.manager.collect(wait=True)
                self.beamline.mca.configure(
                    cooling=True, energy=self.config.roi_energy, edge=self.config.edge_energy, nozzle=True, dark=True
                )
                self.beamline.attenuator.set(self.config.attenuation)
                self.beamline.energy.wait()
                self.beamline.bragg_energy.wait()
                self.beamline.goniometer.wait(start=False)
                self.emit("progress", 0.02, "Waiting for beam to stabilize ...")
                time.sleep(3)
                self.beamline.fast_shutter.open()

                total = len(self.config.positions)
                self.config['start_time'] = datetime.now(tz=pytz.utc)
                for i, x in enumerate(self.config.positions):
                    if self.paused:
                        while self.paused and not self.stopped:
                            time.sleep(0.1)
                        self.beamline.manager.collect(wait=True)
                        self.beamline.mca.configure(cooling=True, nozzle=True)
                        time.sleep(1)  # wait for nozzle to move out.
                    if self.stopped:
                        break

                    self.beamline.bragg_energy.move_to(x, wait=True)
                    y, i0 = multi_count(self.config.exposure, self.beamline.mca, self.beamline.i0)
                    counts = self.beamline.mca.get_roi_counts() + (i0,)
                    self.beamline.mca.get_roi_counts()

                    if i == 0:
                        ref_value = i0
                    counts = (y * ref_value / i0, ) + counts
                    row = (x,) + counts
                    self.raw_data.append(row)
                    self.emit("new-point", row)
                    self.emit("progress", (i + 1.0) /total, "")
                    time.sleep(0)
            except ValueError as e:
                self.emit("error", "Scan Error!")
                logger.error(e)
            finally:
                self.beamline.energy.move_to(self.config.edge_energy)
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.mca.configure(cooling=False, nozzle=False)
                logger.info('Edge scan done.')
                self.beamline.manager.collect()

    def finalize(self):
        self.data = numpy.array(self.raw_data, dtype=self.data_type)
        self.save(self.config.filename)
        if self.stopped:
            self.save_metadata()
        else:
            logger.info("Scan complete. Performing Analyses")
            success = self.analyse()
            if success:
                self.save_metadata()

    def analyse(self):
        self.chooch.configure(self.config, self.data)
        report = self.chooch.run()
        if report:
            self.results['choices'] = report['choices']
            self.results['esf'] = {
                k: report['esf'][k].tolist() for k in report['esf'].dtype.names
            }
            # save to file
            filename = os.path.join(self.config.directory, '{}.mad'.format(self.config['name']))
            with open(filename, 'w') as handle:
                json.dump(self.results, handle)
                logger.info("MAD Analysis Saved: {}".format(filename))
                return True
        else:
            self.emit('error', 'MAD Analysis Failed')
            return False

    def prepare_xdi(self):
        xdi_data = super().prepare_xdi()
        element, edge = self.config['edge'].split('-')
        xdi_data['Element.symbol'] = element
        xdi_data['Element.edge'] = edge
        xdi_data['Scan.edge_energy'] = self.config.edge_energy, 'keV'
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(
            self.config.edge_energy, self.beamline.config['mono_unit_cell']
        )
        return xdi_data

    def save_metadata(self, upload=True):
        params = self.config
        metadata = {
            'name': params['name'],
            'frames': "",
            'filename': os.path.basename(params['filename']),
            'container': params['container'],
            'port': params['port'],
            'start_time': params['start_time'].isoformat(),
            'end_time': params['end_time'].isoformat(),
            'type': 'MAD',
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


class XASScan(BasicScan):
    """
    X-Ray Absorption Spectroscopy (XAS, XANES, EXAFS). Monochromator is scanned around a specific  absorption-edge
    in a stepwise manner and the total _emission for the selected absorption-edge is recorded.
    """

    def __init__(self):
        super().__init__()
        self.emissions = scitools.get_energy_database()
        self.total_time = 0
        self.scan_index = 0

    def configure(self, info):
        self.config = copy.deepcopy(info)
        self.config['edge_energy'], self.config['roi_energy'] = self.emissions[info['edge']]
        self.config['frame_template'] = '{}-{}_{}.xdi'.format(info['name'], info['edge'], '{:0>3d}')
        self.config['frame_glob'] = '{}-{}_{}.xdi'.format(info['name'], info['edge'], '*')
        self.config['targets'] = scitools.exafs_targets(self.config['edge_energy'], kmax=info['kmax'])
        self.config['user'] = misc.get_project_name()
        self.results = {}
        if not os.path.exists(self.config['directory']):
            os.makedirs(self.config['directory'])

    def prepare_for_scan(self):
        self.emit("progress", 0.001, "Preparing devices ...")
        self.beamline.energy.move_to(self.config['edge_energy'])
        self.beamline.manager.collect(wait=True)
        self.beamline.multi_mca.configure(
            cooling=True, energy=self.config['roi_energy'], edge=self.config['edge_energy'], nozzle=True
        )
        self.beamline.attenuator.set(self.config['attenuation'])
        self.beamline.energy.wait()
        self.beamline.bragg_energy.wait()
        self.beamline.goniometer.wait(start=False)
        self.emit("progress", 0.002, "Waiting for beam to stabilize ...")
        time.sleep(3)

    def scan(self):
        logger.info('Scan waiting for beamline to become available.')

        with self.beamline.lock:
            saved_attenuation = self.beamline.attenuator.get()
            self.raw_data = []
            self.results = {'data': [], 'scans': []}
            try:
                self.emit('started', None)
                self.prepare_for_scan()
                self.beamline.fast_shutter.open()
                self.beamline.fast_shutter.open()

                # calculate k and time for each target point
                self.total_time = 1.0
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
                self.config['start_time'] = datetime.now(tz=pytz.utc)
                for scan in range(self.config['scans']):
                    self.scan_index = scan + 1
                    for i, x, k, t in targets_times:
                        if self.paused:
                            self.emit('paused', True, '')
                            logger.warning("Edge Scan paused at point %s." % str(x))
                            while self.paused and not self.stopped:
                                time.sleep(0.05)

                            self.beamline.manager.collect(wait=True)
                            self.beamline.multi_mca.configure(nozzle=True, cooling=True)
                            self.emit('paused', False, '')
                            logger.info("Scan resumed.")
                        if self.stopped:
                            logger.info("Scan stopped!")
                            break

                        self.beamline.bragg_energy.move_to(x, wait=True)
                        y, i0 = multi_count(self.beamline.multi_mca, self.beamline.i0, t)
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
                        self.raw_data.append(tuple(data_point))
                        used_time += t
                        self.emit("new-point", (x, y * scale, y, i0))
                        msg = "Scan {}/{}:  Point {}/{}...".format(scan + 1, self.config['scans'], i, scan_length)
                        self.emit("progress", used_time / self.total_time, msg)
                        time.sleep(0)
                    data = self.set_data(self.raw_data)
                    self.results['data'].append(data)
                    self.config['end_time'] = datetime.now()
                    filename = os.path.join(self.config['directory'], self.config['frame_template'].format(scan + 1))
                    self.save(filename)
                    self.analyse()
                    self.emit('new-row', scan + 1)
                    self.raw_data = []

                if self.stopped:
                    logger.warning("Scan stopped.")
                    self.emit("stopped", None)

                else:
                    logger.info("Scan complete.")
                    self.emit("done", None)
                self.save_metadata()

            finally:
                self.beamline.energy.move_to(self.config['edge_energy'])
                self.beamline.fast_shutter.close()
                self.beamline.attenuator.set(saved_attenuation)
                self.beamline.multi_mca.configure(cooling=False, nozzle=False)
                logger.info('Edge scan done.')
                self.beamline.manager.collect()
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
        x_peak = x[y == y_peak][0]
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
        xdi_data = super().prepare_xdi()
        element, edge = self.config['edge'].split('-')
        xdi_data['Element.symbol'] = element
        xdi_data['Element.edge'] = edge
        xdi_data['Scan.edge_energy'] = self.config['edge_energy'], 'keV'
        xdi_data['Mono.d_spacing'] = converter.energy_to_d(
            self.config['edge_energy'],  self.beamline.config['mono_unit_cell']
        )
        xdi_data['Scan.series'] = '{} of {}'.format(self.scan_index, self.config['scans'])
        return xdi_data

    def save_metadata(self, upload=True):
        params = self.config
        info = datatools.dataset_from_files(params['directory'], params['frame_glob'])
        if info['num_frames']:
            metadata = {
                'name': params['name'],
                'frames': info['frames'],
                'filename': params['frame_template'],
                'container': params['container'],
                'port': params['port'],
                'start_time': params['start_time'].isoformat(),
                'end_time': params['end_time'].isoformat(),
                'type': 'XAS',
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
