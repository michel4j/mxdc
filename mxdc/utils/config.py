from gi.repository import Gio
from mxdc.utils import json
from mxdc.utils.log import get_module_logger
from datetime import date, datetime
import os
import atexit

_logger = get_module_logger('mxdc.config')

CONFIG_DIR = os.path.join(os.environ['HOME'], '.config', 'mxdc')
SESSION_CONFIG_FILE = '{}.conf'.format(os.environ['MXDC_CONFIG'])
SCHEMA_DIR = os.path.join(os.environ['MXDC_PATH'], 'etc', 'schemas')

_schema_source = Gio.SettingsSchemaSource.new_from_directory(
    SCHEMA_DIR,
    Gio.SettingsSchemaSource.get_default(),
    False
)
_schema = _schema_source.lookup('ca.lightsource.mxdc', False)

settings = Gio.Settings.new_full(_schema, None, None)

def load_config(fname):
    config_file = os.path.join(CONFIG_DIR, fname)
    if os.path.exists(config_file):
        with open(config_file, 'r') as handle:
            config = json.load(handle)
    else:
        config = {}
    return config

def save_config(fname, config):
    if not os.path.exists(CONFIG_DIR):
        os.mkdir(CONFIG_DIR)
    config_file = os.path.join(CONFIG_DIR, fname)
    with open(config_file, 'w') as handle:
        json.dump(config, handle, indent=4)


def get_session():
    config = load_config(SESSION_CONFIG_FILE)
    today = date.today()
    prev_date_string = config.get('session-start', '19900101')
    prev_date = datetime.strptime(prev_date_string, '%Y%m%d').date()
    if (today - prev_date).days > 6 or not 'session-key' in config:
        date_string = today.strftime('%Y%m%d')
        config['session-key'] ='{}-{}'.format(os.environ['MXDC_CONFIG'], date_string)
        config['session-start'] = date_string
        save_config(SESSION_CONFIG_FILE, config)
    return config['session-key']




