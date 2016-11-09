'''
Created on Oct 28, 2010

@author: michel
'''

from twisted.spread import pb
from twisted.internet import reactor

from bcm.utils import mdns
from bcm.utils.log import get_module_logger
from bcm.service.base import BaseService
from bcm.utils.misc import get_project_name
import requests


import re
from dpm.service import common
import gobject
import os
import json

_logger = get_module_logger(__name__)

class DPMClient(BaseService):
    def __init__(self, address=None):
        BaseService.__init__(self)
        self.name = "AutoProcess Service"
        self._service_found = False
        self._ready = False
        if address is not None:
            m = re.match('([\w.\-_]+):(\d+)', address)
            if m:
                data = {'name': 'AutoProcess Service',
                        'host': m.group(1),
                        'address': m.group(1),
                        'port': int(m.group(2)),
                        }
            self.on_dpm_service_added(None, data)
        else:
            gobject.idle_add(self.setup)
    
    def on_dpm_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        _logger.info('AutoProcess Service found at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_dpm_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def on_dpm_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        self._ready = False
        _logger.warning('AutoProcess Service %s:%s disconnected.' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.set_state(active=False)
        
    def setup(self):
        """Find out the connection details of the AutoProcess Server using mdns
        and initiate a connection"""
        import time
        _service_data = {'user': os.getlogin(), 
                         'uid': os.getuid(), 
                         'gid': os.getgid(), 
                         'started': time.asctime(time.localtime())}
        self.browser = mdns.Browser('_cmcf_dpm._tcp')
        self.browser.connect('added', self.on_dpm_service_added)
        self.browser.connect('removed', self.on_dpm_service_removed)
        
    def on_dpm_connected(self, perspective):
        """ I am called when a connection to the AutoProcess Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server."""
        _logger.info('Connection to AutoProcess Server established')
        self.service = perspective
        self.service.notifyOnDisconnect(self._disconnect_cb)     
        self._ready = True
        self.set_state(active=True)
    
    def _disconnect_cb(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)
        
    def on_connection_failed(self, reason):
        _logger.error('Could not connect to AutoProcess Server: %', reason)
    
    def is_ready(self):
        return self._ready

    def dump_results(self, data):
        """pretty print the data received from the server"""
        import pprint
        pp = pprint.PrettyPrinter(indent=4, depth=4)
        _logger.info('Server sent: %s' % pp.pformat(data))

    def dump_error(self, failure):
        r = failure.trap(common.InvalidUser, common.CommandFailed)
        _logger.error('<%s -- %s>.' % (r, failure.getErrorMessage()))


class LIMSClient(BaseService):
    def __init__(self, address):
        BaseService.__init__(self)
        self.name = "MxLIVE Service"
        self.address = address
        self.cookies = {}
        self.set_state(active=True)
        _logger.info('MxLIVE Service configured for %s' % (address))

    def is_ready(self):
        return True

    def get(self, *args, **kwargs):
        r = requests.get(*args, verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            reply = r.json()
        else:
            r.raise_for_status()
        return reply

    def post(self, *args, **kwargs):
        r = requests.post(*args, verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            reply = r.json()
        else:
            print r.text
            r.raise_for_status()
        return reply

    def get_project_samples(self, beamline):
        url = "{}/api/{}/samples/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key',''), beamline.name, get_project_name()
        )
        try:
            reply = self.get(url)
        except (IOError, ValueError, requests.HTTPError) as e:
            _logger.error('Unable to fetch Samples from MxLIVE: \n %s' % e)
            reply = {'error': 'Unable to fetch Samples from MxLIVE', 'details': '{}'.format(e)}
        return reply



    def upload_dataset(self, beamline, data):
        url = "{}/api/{}/data/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key',''), beamline.name, get_project_name()
        )

        json_info = {
            'id': data.get('id'),
            'name': data['name'],
            'resolution': round(data['resolution'], 5),
            'start_angle': data['start_angle'],
            'delta_angle': data['delta_angle'],
            'first_frame': data['first_frame'],
            'frame_sets': data['frame_sets'],
            'exposure_time': data['exposure_time'],
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
        if data.get('crystal_id'):
            json['crystal_id'] = int(data['crystal_id'])
        if data['num_frames'] < 10:
            json_info['kind'] = 0  # screening
        else:
            json_info['kind'] = 1  # collection

        if data['num_frames'] >= 2:
            try:
                reply = self.post(url, json=json_info)
            except (IOError, ValueError, requests.HTTPError), e:
                _logger.error('Dataset meta-data could not be uploaded to MxLIVE, \n {}'.format(e))
            else:
                if reply.get('id') is not None:
                    data['id'] = reply['id']
                    _logger.info('Dataset meta-data uploaded to MxLIVE.')
                else:
                    _logger.error('Invalid Response from MxLIVE: {}'.format(reply))

        with open(os.path.join(data['directory'], '%s.SUMMARY' % data['name']), 'w') as fobj:
            json.dump(data, fobj, indent=4)

        return

    def upload_datasets(self, beamline, datasets):
        for data in datasets:
            self.upload_dataset(beamline, data)
        return

    def upload_scan(self, beamline, scan):
        url = "{}/api/{}/scan/{}/{}/".format(
            self.address, beamline.config.get('lims_api_key',''), beamline.name, get_project_name()
        )
        kind = int(scan.get('kind'))

        if kind == 1:  # Excitation Scan
            crystal_id = None if not scan['parameters'].get('crystal_id', '') else int(scan['parameters']['crystal_id'])
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
        except (IOError, ValueError, requests.HTTPError), e:
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
            self.address, beamline.config.get('lims_api_key',''), beamline.name, get_project_name()
        )
        if report.get('data_id'):
            try:
                reply = self.post(url, json=report)
            except (IOError, ValueError, requests.HTTPError), e:
                _logger.error('Dataset could not be uploaded to MxLIVE, \n {}'.format(e))
            else:
                if reply.get('id'):
                    report['id'] = reply['id']
                    _logger.info('Dataset successfully uploaded to MxLIVE')
                else:
                    _logger.error('Invalid response from to MxLIVE: {}'.format(reply))
        else:
            _logger.error('Dataset required to upload report, none found.')
        return reply

    def upload_reports(self, beamline, reports):
        for data in reports:
            report = data['result']
            self.upload_report(beamline, report)

        if len(reports):
            with open(os.path.join(report['url'], 'process.json'), 'w') as fobj:
                info = {'result': reports, 'error': None}
                json.dump(info, fobj)

        return reports


