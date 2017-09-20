'''
Created on Mar 16, 2011

@author: michel
'''
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_project_name
from mxdc.utils import json
import os


logger = get_module_logger(__name__)


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
        if json_info['crystal_id'] is None:
            json_info['experiment_id'] = None 
        if result['num_frames'] < 10:
            json_info['kind'] = 0 # screening
        else:
            json_info['kind'] = 1 # collection
        
        if result['num_frames'] >= 4:
            try:     
                reply = beamline.lims.service.lims.add_data(
                        beamline.config.get('lims_api_key',''), json_info)
            except IOError:
                reply = {'error': 'Unable to connect to MxLIVE'}
            if reply.get('result') is not None:
                if reply['result'].get('data_id') is not None:
                    # save data id to file so next time we can find it
                    result['id'] = reply['result']['data_id']
                    logger.info('Dataset meta-data uploaded to MxLIVE.')
            elif reply.get('error') is not None:
                print reply.get('error')
                logger.error('Dataset meta-data could not be uploaded to MxLIVE.')
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
        try:    
            reply = beamline.lims.service.lims.add_report(
                    beamline.config.get('lims_api_key',''), report['result'])
        except IOError:
            reply = {'error': 'Unable to connect to MxLIVE'}
        
        if reply.get('result') is not None:
            if reply['result'].get('result_id') is not None:
                # save data id to file so next time we can find it
                report['result']['id'] = reply['result']['result_id']
                logger.info('Processing Report uploaded to MxLIVE.')
        elif reply.get('error') is not None:
            logger.error('Processing report could not be uploaded to MxLIVE.')

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

def upload_scan(beamline, results):
    for scan in results:
        scan['project_name'] = get_project_name()
        kind = scan.get('kind')
        if kind == 1: # Excitation Scan
            new_info = {
                'details': {
                    'energy': scan['data'].get('energy'),
                    'counts': scan['data'].get('counts'),
                    'fit': scan['data'].get('fit'),
                    'peaks': scan.get('assigned'),
                    },
                'name': scan['parameters'].get('prefix'),
                'crystal_id': scan['parameters'].get('crystal_id'),
                'exposure_time': scan['parameters'].get('exposure_time'),
                'attenuation': scan['parameters'].get('attenuation'),
                'edge': scan['parameters'].get('edge'),
                'energy': scan['parameters'].get('energy'),
                }
        elif kind is 0: # MAD Scan
            new_info = {
                'details': {
                    'energies': [scan['energies'].get('peak'),scan['energies'].get('infl'),scan['energies'].get('remo')],
                    'efs': scan.get('efs'),
                    'data': scan.get('data'),
                    },
                'name': scan.get('name_template'),
                'crystal_id': scan.get('crystal_id'),
                'attenuation': scan.get('attenuation'),
                'edge': scan.get('edge'),
                'energy': scan.get('energy')
                }
        # General information
        new_info['kind'] = kind
        new_info['beamline_name'] = beamline.name
        new_info['project_name'] = get_project_name()
        
        try:          
            reply = beamline.lims.service.lims.add_scan(
                    beamline.config.get('lims_api_key',''), new_info)
            logger.info('Scan uploaded to MxLIVE.')
        except IOError, e:
            logger.error('Scan could not be uploaded to MxLIVE')
            reply = {'error': 'Unable to connect to MxLIVE %s' % e}
        
    return reply

def get_onsite_samples(beamline):
    info = {
        'project_name': get_project_name(),
        'beamline_name': beamline.name }
    try:
        reply = beamline.lims.service.lims.get_onsite_samples(beamline.config.get('lims_api_key',''), info)
    except (IOError, ValueError) as e:
        logger.error('Unable to fetch samples: %s' % e)
        reply = {'error': {'message': str(e)}}       
    return reply


__all__ = ['upload_report', 'upload_data', 'get_onsite_samples']
