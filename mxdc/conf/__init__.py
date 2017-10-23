import glob
import os
import sys

import msgpack
from gi.repository import Gio

from mxdc.utils import misc, ipaddress
from mxdc.utils.log import get_module_logger, log_to_console

logger = get_module_logger(__name__)
log_to_console()

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARE_DIR = os.path.join(APP_DIR, 'share')
CONFIG_DIR = os.path.join(APP_DIR, 'etc')
DOCS_DIR = os.path.join(APP_DIR, 'docs/html')

APP_CACHE_DIR = ''
CONFIGS = ''
Settings = None
SettingKeys = None
PROPERTIES = None



def _extract_variable(mod_path, variable, default=None):
    import ast
    with open(mod_path, "r") as file_mod:
        data = file_mod.read()
    try:
        ast_data = ast.parse(data, filename=mod_path)
    except:
        return default

    if ast_data:
        for body in ast_data.body:
            proceed = (
                body.__class__ == ast.Assign and
                len(body.targets) == 1 and
                getattr(body.targets[0], "id", "") == variable
            )
            if proceed:
                try:
                    return ast.literal_eval(body.value)
                except:
                    return default
    return default


def get_config_modules(config_dir, name=None):
    config_modules = [
        (mod, mod.replace('.py', '_local.py')) for mod in glob.glob(os.path.join(config_dir, '*.py'))
        if '_local' not in mod
    ]
    entries = {
        (gmod, lmod): _extract_variable(gmod, 'CONFIG')
        for gmod, lmod in config_modules
    }

    host = misc.get_address()
    for mods, entry in entries.items():
        if name:
            if entry['name'] == name:
                return mods, entry
        else:
            subnet_text = u'{}'.format(entry.get('subnet', '0.0.0.0/32'))
            subnet = ipaddress.ip_network(subnet_text)
            if host in subnet:
                return mods, entry
    return None, {}


def initialize(name=None):
    global CONFIGS, Settings, SettingKeys, APP_CACHE_DIR, PROPERTIES

    app_config_dir = os.path.join(misc.get_project_home(), '.config', 'mxdc')
    try:
        # initiallize users settings
        if not os.path.exists(app_config_dir):
            os.makedirs(app_config_dir, mode=0o700)

        schema_source = Gio.SettingsSchemaSource.new_from_directory(
            SHARE_DIR, Gio.SettingsSchemaSource.get_default(), False
        )
        schema = schema_source.lookup('org.mxdc', False)
        SettingKeys = {
            setting: schema.get_key(setting)
            for setting in schema.list_keys()
        }
        Settings = Gio.Settings.new_full(schema, None, None)

        # get config modules
        CONFIGS, PROPERTIES = get_config_modules(CONFIG_DIR, name=name)
        assert bool(CONFIGS), 'Configuration error'
        APP_CACHE_DIR = os.path.join(app_config_dir, '{}.cache'.format(misc.short_hash(PROPERTIES['name'])))

        for dir in [app_config_dir, APP_CACHE_DIR]:
            if not os.path.exists(dir):
                os.makedirs(dir, mode=0o700)
    except Exception as e:
        logger.error('Could not find Beamline Configuration.')
        logger.error('Please make sure MXDC is properly installed and configured.')
        logger.error(e)
        sys.exit()
    else:
        logger.info('Starting MXDC ({})... '.format(PROPERTIES['name']))


def load_cache(realm):
    cache_file = os.path.join(APP_CACHE_DIR, realm)
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as handle:
            data = msgpack.load(handle)
        return data
    return {}


def save_cache(data, realm):
    with open(os.path.join(APP_CACHE_DIR, realm), 'w') as handle:
        msgpack.dump(data, handle)


def clear_cache(keep_session=True):
    for cache_file in os.listdir(APP_CACHE_DIR):
        if keep_session and cache_file == 'session': continue
        file_path = os.path.join(APP_CACHE_DIR, cache_file)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.error('Unable to clear cache.')
