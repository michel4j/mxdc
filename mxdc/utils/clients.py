import json
import os
import re

from gi.repository import GObject
import requests
from mxdc.service.base import BaseService
from mxdc.utils import mdns
from mxdc.utils.misc import get_project_name
from mxdc.utils.log import get_module_logger
from twisted.internet import reactor, error
from twisted.spread import pb

_logger = get_module_logger(__name__)


# For some reason clientConnectionMade is not called
class ServerClientFactory(pb.PBClientFactory):
    def buildProtocol(self, addr):
        broker = pb.PBClientFactory.buildProtocol(self, addr)
        pb.PBClientFactory.clientConnectionMade(self, broker)
        return broker


class DPMClient(BaseService):
    def __init__(self, address=None):
        BaseService.__init__(self)
        self.name = "AutoProcess Service"
        self._service_found = False
        self._service_data = {}
        self._ready = False
        if address is not None:
            m = re.match('([\w.\-_]+):(\d+)', address)
            if m:
                data = {'name': 'AutoProcess Service',
                        'host': m.group(1),
                        'address': m.group(1),
                        'port': int(m.group(2)),
                        }
                self.on_service_added(None, data)
        else:
            GObject.idle_add(self.setup)

    def on_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        self.factory = ServerClientFactory()  # pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_connected).addErrback(self.on_connection_failed)
        reactor.connectTCP(self._service_data['address'], self._service_data['port'], self.factory)
        _logger.info(
            'AutoProcess Service found at {}:{}'.format(self._service_data['host'], self._service_data['port'])
        )

    def on_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host'] == data['host']:
            return
        self._service_found = False
        self._ready = False
        _logger.warning(
            'AutoProcess Service {}:{} disconnected.'.format(self._service_data['host'], self._service_data['port'])
        )
        self.set_state(active=False)

    def setup(self):
        """Find out the connection details of the AutoProcess Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_dpm._tcp')
        self.browser.connect('added', self.on_service_added)
        self.browser.connect('removed', self.on_service_removed)

    def on_connected(self, perspective):
        """ I am called when a connection to the AutoProcess Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server."""
        _logger.info('Connection to AutoProcess Server established')
        self.service = perspective
        self.service.notifyOnDisconnect(self.on_disconnected)
        self._ready = True
        self.set_state(active=True)

    def on_disconnected(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)

    def on_connection_failed(self, reason):
        _logger.error('Connection to AutoProcess Server Failed')

    def is_ready(self):
        return self._ready


class LIMSClient(BaseService):
    def __init__(self, address):
        BaseService.__init__(self)
        self.name = "MxLIVE Service"
        self.address = address
        self.cookies = {}
        self.set_state(active=True)
        _logger.info('MxLIVE Service configured for {}'.format(address))

    def is_ready(self):
        return True

    def get(self, *args, **kwargs):
        r = requests.get(*args, verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            r.raise_for_status()

    def post(self, *args, **kwargs):
        r = requests.post(*args, verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            _logger.error('Failed posting data to MxLIVE: HTTP-{}'.format(r.status_code))
            r.raise_for_status()

    def get_project_samples(self, beamline):
        _logger.debug('Requesting Samples from MxLIVE ...')
        url = "{}/api/{}/samples/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key', ''), beamline.name, get_project_name()
        )
        try:
            reply = self.get(url)
        except (IOError, ValueError, requests.HTTPError) as e:
            _logger.error('Unable to fetch Samples from MxLIVE: \n {}'.format(e))
            reply = {'error': 'Unable to fetch Samples from MxLIVE', 'details': '{}'.format(e)}
        return reply

    def upload_dataset(self, beamline, data):
        url = "{}/api/{}/data/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key', ''), beamline.name, get_project_name()
        )

        json_info = {
            'id': data.get('id'),
            'name': data['name'],
            'resolution': round(data['resolution'], 5),
            'start_angle': data['start'],
            'delta_angle': data['delta'],
            'first_frame': data['first'],
            'frame_sets': data['frame_sets'],
            'exposure_time': data['exposure'],
            'two_theta': data['two_theta'],
            'wavelength': round(data['wavelength'], 5),
            'detector': data['detector'],
            'detector_size': data['detector_size'],
            'pixel_size': data['pixel_size'],
            'beam_x': data['beam_x'],
            'beam_y': data['beam_y'],
            'url': data['directory'],
            'staff_comments': data.get('comments'),
        }
        if data.get('sample_id'):
            json_info['sample_id'] = int(data['sample_id'])
        if data['num_frames'] < 10:
            json_info['kind'] = 0  # screening
        else:
            json_info['kind'] = 1  # collection

        if data['num_frames'] >= 2:
            try:
                reply = self.post(url, json=json_info)
            except (IOError, ValueError, requests.HTTPError) as e:
                _logger.error('Dataset meta-data could not be uploaded to MxLIVE, \n {}'.format(e))
            else:
                if reply.get('id') is not None:
                    data['id'] = reply['id']
                    _logger.info('Dataset meta-data uploaded to MxLIVE.')
                else:
                    _logger.error('Invalid Response from MxLIVE: {}'.format(reply))

        with open(os.path.join(data['directory'], '{}.SUMMARY'.format(data['name'])), 'w') as fobj:
            json.dump(data, fobj, indent=4)

        return

    def upload_datasets(self, beamline, datasets):
        for data in datasets:
            self.upload_dataset(beamline, data)
        return

    def upload_scan(self, beamline, scan):
        url = "{}/api/{}/scan/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key', ''), beamline.name, get_project_name()
        )
        kind = int(scan.get('kind'))
        new_info = {}

        if kind == 1:  # Excitation Scan
            crystal_id = None if not scan['parameters'].get('sample_id', '') else int(scan['parameters']['sample_id'])
            new_info = {
                'kind': kind,
                'details': {
                    'energy': scan['data'].get('energy'),
                    'counts': scan['data'].get('counts'),
                    'fit': scan['data'].get('fit'),
                    'peaks': scan.get('assigned'),
                },
                'name': scan['parameters'].get('prefix'),
                'crystal_id': crystal_id,
                'exposure_time': scan['parameters'].get('exposure_time'),
                'attenuation': scan['parameters'].get('attenuation'),
                'edge': scan['parameters'].get('edge'),
                'energy': scan['parameters'].get('energy'),
            }
        elif kind is 0:  # MAD Scan
            crystal_id = None if not scan.get('crystal_id', '') else int(scan['crystal_id'])
            new_info = {
                'kind': kind,
                'details': {
                    'energies': [scan['energies'].get('peak'), scan['energies'].get('infl'),
                                 scan['energies'].get('remo')],
                    'efs': scan.get('efs'),
                    'data': scan.get('data'),
                },
                'name': scan.get('name_template'),
                'crystal_id': crystal_id,
                'exposure_time': scan.get('exposure_time'),
                'attenuation': scan.get('attenuation'),
                'edge': scan.get('edge'),
                'energy': scan.get('energy')
            }

        try:
            reply = self.post(url, json=new_info)
        except (IOError, ValueError, requests.HTTPError) as e:
            _logger.error('Scan could not be uploaded to MxLIVE, \n {}'.format(e))
        else:
            if reply.get('id'):
                new_info['id'] = reply['id']
                _logger.info('Scan successfully uploaded to MxLIVE')
            else:
                _logger.error('Invalid response from to MxLIVE: {}'.format(reply))

        return

    def upload_report(self, beamline, report):
        url = "{}/api/{}/report/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key', ''), beamline.name, get_project_name()
        )
        if report.get('data_id'):
            try:
                reply = self.post(url, json=report)
            except (IOError, ValueError, requests.HTTPError) as e:
                msg = 'Report could not be uploaded to MxLIVE, \n {}'.format(e)
                _logger.error(msg)
                reply = {'error': msg}
            else:
                if reply.get('id'):
                    report['id'] = reply['id']
                    _logger.info('Report successfully uploaded to MxLIVE')
                else:
                    _logger.error('Invalid response from to MxLIVE: {}'.format(reply))
        else:
            msg = 'Dataset required to upload report, none found.'
            reply = {'error': msg}
            _logger.error(msg)
        return reply

    def upload_reports(self, beamline, reports):
        for data in reports:
            report = data['result']
            self.upload_report(beamline, report)

        if reports:
            result = reports[0]['result']
            with open(os.path.join(result['url'], 'process.json'), 'w') as fobj:
                info = {'result': reports, 'error': None}
                json.dump(info, fobj)

        return reports


class MxDCClient(BaseService):
    def __init__(self, service_type):
        BaseService.__init__(self)
        self.name = "Remote MxDC"
        self._service_found = False
        self.added_id = None
        self.removed_id = None
        self.service_data = {}
        self.service = None
        self._ready = False
        self.service_type = service_type
        GObject.idle_add(self.setup)

    def on_service_added(self, obj, data):
        self._service_found = True
        self.service_data = data
        self.factory = ServerClientFactory()  # pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_connected).addErrback(self.on_connection_failed)
        reactor.connectTCP(self.service_data['address'], self.service_data['port'], self.factory)

        _logger.warning(
            'Remote MXDC instance {}@{}:{} since {}'.format(
                self.service_data['data']['user'], self.service_data['address'], self.service_data['port'],
                self.service_data['data']['started']
            )
        )

    def on_service_removed(self, obj, data):
        # if not self._service_found and self.service_data['address'] == data['address']:
        #     return
        self._service_found = False
        self._ready = False
        self.set_state(active=False)
        self.notify_failure()

    def setup(self):
        """Find out the connection details of the Remove MXDC using mdns
        and initiate a connection"""
        self.browser = mdns.Browser(self.service_type)
        self.added_id = self.browser.connect('added', self.on_service_added)
        self.removed_id = self.browser.connect('removed', self.on_service_removed)
        GObject.timeout_add(2000, self.notify_failure)

    def on_connected(self, perspective):
        """ I am called when a connection to the MxDC instance has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the MxDC instance."""
        self.service = perspective
        self.service.notifyOnDisconnect(self.on_disconnected)
        self._ready = True
        self.set_state(active=True)

    def on_disconnected(self, remote):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)

    def on_connection_failed(self, reason):
        reason.trap(error.ConnectionDone)
        _logger.warning('Connection to Remote MxDC Failed')

    def notify_failure(self):
        if not self.active_state:
            self.browser.disconnect(self.removed_id)
            self.browser.disconnect(self.added_id)
            self.set_state(health=(16, 'not-connected'))

    def is_ready(self):
        return self._ready


__all__ = ['DPMClient', 'MxDCClient', 'LIMSClient']
