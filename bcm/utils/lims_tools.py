'''
Created on Mar 16, 2011

@author: michel
'''
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_project_name
import os

try:
    import json
except:
    import simplejson as json

_logger = get_module_logger(__name__)


def upload_data(beamline, results):
    for result in results:
        json_info = {
            'id': result.get('id'),
            'crystal_id': result.get('crystal_id'),
            'experiment_id': result.get('experiment_id'),
            'name': result['name'],
            'resolution': round(result['resolution'], 5),
            'start_angle': result['start_angle'],
            'delta_angle': result['delta_angle'],
            'first_frame': result['first_frame'],
            'frame_sets': result['frame_sets'],
            'exposure_time': result['exposure_time'],
            'two_theta': result['two_theta'],
            'wavelength': round(result['wavelength'], 5),
            'detector': result['detector'],
            'beamline_name': result['beamline_name'],
            'detector_size': result['detector_size'],
            'pixel_size': result['pixel_size'],
            'beam_x': result['beam_x'],
            'beam_y': result['beam_y'],
            'url': result['directory'],
            'staff_comments': result.get('comments'),                 
            'project_name': get_project_name(),                  
            }
        if result['num_frames'] < 10:
            json_info['kind'] = 0 # screening
        else:
            json_info['kind'] = 1 # collection
        
        if result['num_frames'] >= 4:
            reply = beamline.lims_server.lims.add_data(
                        beamline.config.get('lims_api_key',''), json_info)
            if reply.get('result') is not None:
                if reply['result'].get('data_id') is not None:
                    # save data id to file so next time we can find it
                    result['id'] = reply['result']['data_id']
                    _logger.info('Dataset uploaded to LIMS.')
            elif reply.get('error') is not None:
                _logger.error('Dataset could not be uploaded to LIMS.')
        filename = os.path.join(result['directory'], '%s.SUMMARY' % result['name'])
        fh = open(filename,'w')
        json.dump(result, fh, indent=4)
        fh.close()
    return results


def upload_report(beamline, results):
    for report in results:
        if report['result'].get('data_id') is None:
            continue
        report['result'].update(project_name = get_project_name())            
        reply = beamline.lims_server.lims.add_report(
                    beamline.config.get('lims_api_key',''), report['result'])
        if reply.get('result') is not None:
            if reply['result'].get('result_id') is not None:
                # save data id to file so next time we can find it
                report['result']['id'] = reply['result']['result_id']
                _logger.info('Processing Report uploaded to LIMS.')
        elif reply.get('error') is not None:
            _logger.error('Processing report could not be uploaded to LIMS.')

    #TODO: Investigate, potential issue with merged processing and MAD datasets
    filename = os.path.join(report['result']['url'], 'process.json')
    info = {
        'result': results,
        'error': None,
    }

    fh = open(filename,'w')
    json.dump(info, fh)
    fh.close()
    return results
