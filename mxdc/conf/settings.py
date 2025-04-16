import os
import string
from datetime import date
from pathlib import Path

import msgpack
import numpy

from mxdc.conf import CONFIGS, APP_CACHE_DIR, Settings, SettingSchema, PROPERTIES
from mxdc.conf import load_cache, save_cache, clear_cache

if not CONFIGS:
    raise ImportError('Configuration system not initialized. Run conf.initialize() before importing settings')

DEBUG = bool(os.environ.get('MXDC_DEBUG'))


def get_string(*args):
    return Settings.get_string(*args)


def get_configs():
    return CONFIGS


def fetch_keys(file_name):
    key_file = Path(APP_CACHE_DIR).parent / file_name
    data = None
    if not key_file.exists():
        return data
    try:
        with open(key_file, 'rb') as handle:
            if file_name.endswith('.dsa'):
                data = msgpack.load(handle, raw=True)
                data = {
                    key.decode('utf-8'): value for key, value in data.items()
                }
            else:
                data = msgpack.load(handle)

    except msgpack.UnpackException as e:
        data = None
    return data


def save_keys(keys, file_name):
    key_file = Path(APP_CACHE_DIR).parent / file_name
    with open(key_file, 'wb') as handle:
        msgpack.dump(keys, handle)


def get_session():
    realm = 'session'
    config = load_cache(realm)
    today = date.today()
    isodate = today.isocalendar()

    if DEBUG:
        this_week = [isodate.year, (isodate.week - 1) * 7 + isodate.weekday // 2]
        session_week = config.get('session-week', [1990, 1])
    else:
        this_week = [isodate.year, isodate.week]
        session_week = config.get('session-week', [1990, 1])

    if (this_week != session_week) or 'session-key' not in config:
        date_string = today.strftime('%Y%m%d')
        token = ''.join(numpy.random.choice(list(string.digits + string.ascii_letters), size=8))
        config['session-key'] = '{}-{}-{}'.format(PROPERTIES['name'].replace('-', ''), date_string, token)
        config['session-week'] = this_week
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
