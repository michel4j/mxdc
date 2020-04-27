import os
import string
from datetime import date, datetime

import msgpack
import numpy

from mxdc.conf import CONFIGS, APP_CACHE_DIR, Settings, SettingSchema, PROPERTIES
from mxdc.conf import load_cache, save_cache, clear_cache

if not CONFIGS:
    raise ImportError('Configuration system not initialized. Run conf.initialize() before importing settings')

_KEY_FILE = os.path.join(os.path.dirname(APP_CACHE_DIR), 'keys.dsa')

DEBUG = bool(os.environ.get('MXDC_DEBUG'))


def get_string(*args):
    return Settings.get_string(*args)


def get_configs():
    return CONFIGS


def keys_exist():
    return os.path.exists(_KEY_FILE)


def get_keys():
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import dsa
    from cryptography.hazmat.primitives import serialization
    if not keys_exist():
        key = dsa.generate_private_key(key_size=1024, backend=default_backend())
        data = {
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
    else:
        with open(_KEY_FILE, 'rb') as handle:
            raw_data = msgpack.load(handle, raw=True)
            data = {key.decode('utf-8') if isinstance(key, bytes) else key: value for key, value in raw_data.items()}
    return data


def save_keys(keys):
    if not keys_exist():
        with open(_KEY_FILE, 'wb') as handle:
            msgpack.dump(keys, handle)


def get_session():
    realm = 'session'
    config = load_cache(realm)
    today = date.today()
    prev_date_string = config.get('session-start', '19900101')
    prev_date = datetime.strptime(prev_date_string, '%Y%m%d').date()
    if (today - prev_date).days > 5 or not 'session-key' in config:
        date_string = today.strftime('%Y%m%d')
        token = ''.join(numpy.random.choice(list(string.digits + string.ascii_letters), size=8))
        config['session-key'] = '{}-{}-{}'.format(PROPERTIES['name'].replace('-', ''), date_string, token)
        config['session-start'] = date_string
        clear_cache(False)  # clear the cache if new session
        save_cache(config, realm)
    return config['session-key']


def get_setting_properties(key):
    setting = SettingSchema.get_key(key)
    if not setting:
        return {}
    else:
        return {
            'name': setting.get_name(),
            'description': setting.get_description(),
            'summary': setting.get_summary(),
            'default': setting.get_default_value()
        }
