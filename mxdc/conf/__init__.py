import glob
import os
import sys

from gi.repository import Gio
from mxdc.utils import misc, ipaddress
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)

APP_CONFIG_DIR = os.path.join(os.environ['HOME'], '.config', 'mxdc')
CONFIG_DIR = None
CONFIG_ROOT = None
CONFIGS = None
SETTINGS = None


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
    global CONFIG_DIR, CONFIGS, APP_CONFIG_DIR, CONFIG_ROOT, SETTINGS
    CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'etc')

    try:
        # initiallize users settings
        schema_dir = os.path.join(CONFIG_DIR, 'schemas')
        schema_source = Gio.SettingsSchemaSource.new_from_directory(
            schema_dir, Gio.SettingsSchemaSource.get_default(), False
        )
        schema = schema_source.lookup('ca.lightsource.mxdc', False)
        SETTINGS = Gio.Settings.new_full(schema, None, None)

        # get config modules
        CONFIGS, properties = get_config_modules(CONFIG_DIR, name=name)
        assert bool(CONFIGS), 'Configuration error'
        CONFIG_ROOT = properties['name']
    except:
        logger.error('Could not find Beamline Configuration.')
        logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit()
    else:
        logger.info('Starting MXDC ({})... '.format(CONFIG_ROOT))
