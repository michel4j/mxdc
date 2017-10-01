
import json
import os
from datetime import date, datetime

import msgpack
from mxdc.utils import misc

from . import CONFIGS, CONFIG_ROOT, APP_CONFIG_DIR, SETTINGS

if CONFIGS is None:
    raise ImportError('Configuration system not initialized. Run conf.initialize() before importing settings')

KEY_FILE = os.path.join(APP_CONFIG_DIR, 'keys.dsa')


def get_string(*args):
    SETTINGS.get_string(*args)


def get_configs():
    return CONFIGS


def load_config(fname):
    config_file = os.path.join(APP_CONFIG_DIR, fname)
    if os.path.exists(config_file):
        with open(config_file, 'r') as handle:
            config = json.load(handle)
    else:
        config = {}
    return config


def has_keys():
    return os.path.exists(KEY_FILE)


def fetch_keys():
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import dsa
    from cryptography.hazmat.primitives import serialization
    if not has_keys():
        key = dsa.generate_private_key(key_size=1024, backend=default_backend())
        key_data = {
            'private': key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()
            ),
            'public': key.public_key().public_bytes(
                serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH
            )
        }
        with open(KEY_FILE, 'wb') as handle:
            handle.write(msgpack.packb(key_data))
            os.chmod(KEY_FILE, 0o600)
    else:
        with open(KEY_FILE, 'rb') as handle:
            key_data = msgpack.unpackb(handle.read())
    return key_data


def save_config(fname, config):
    if not os.path.exists(APP_CONFIG_DIR):
        os.mkdir(APP_CONFIG_DIR)
        os.chmod(APP_CONFIG_DIR, 0o700)
    config_file = os.path.join(APP_CONFIG_DIR, fname)
    with open(config_file, 'w') as handle:
        json.dump(config, handle, indent=4)


def get_session():
    session_config_file = os.path.join(APP_CONFIG_DIR, '{}.conf'.format(CONFIG_ROOT))
    config = load_config(session_config_file)
    today = date.today()
    prev_date_string = config.get('session-start', '19900101')
    prev_date = datetime.strptime(prev_date_string, '%Y%m%d').date()
    if (today - prev_date).days > 6 or not 'session-key' in config:
        date_string = today.strftime('%Y%m%d')
        config['session-key'] = '{}-{}'.format(CONFIG_ROOT.replace('-', ''), date_string)
        config['session-start'] = date_string
        save_config(session_config_file, config)
    return config['session-key']


def get_activity_template(activity='{activity}'):
    template = SETTINGS.get_string('directory-template')
    activity_template = template[1:] if template[0] == os.sep else template
    dir_template = os.path.join(misc.get_project_home(), '{session}', activity_template)
    return misc.format_partial(dir_template, activity=activity, session=get_session())



SESSION = get_session()