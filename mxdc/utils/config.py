import os
import msgpack
from datetime import date, datetime

from gi.repository import Gio
from mxdc.utils import json, misc
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)

CONFIG_DIR = os.path.join(os.environ['HOME'], '.config', 'mxdc')
SESSION_CONFIG_FILE = '{}.conf'.format(os.environ['MXDC_CONFIG'])
SCHEMA_DIR = os.path.join(os.environ['MXDC_PATH'], 'etc', 'schemas')
KEY_FILE = os.path.join(CONFIG_DIR, 'keys.dsa')
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
    if not os.path.exists(CONFIG_DIR):
        os.mkdir(CONFIG_DIR)
        os.chmod(CONFIG_DIR, 0o700)
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
        config['session-key'] = '{}-{}'.format(os.environ['MXDC_CONFIG'], date_string)
        config['session-start'] = date_string
        save_config(SESSION_CONFIG_FILE, config)
    return config['session-key']

def get_activity_template(activity='{activity}'):
    template = settings.get_string('directory-template')
    activity_template = template[1:] if template[0] == os.sep else template
    dir_template = os.path.join(misc.get_project_home(), '{session}', activity_template)
    return misc.format_partial(dir_template, activity=activity, session=get_session())