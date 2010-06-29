'''
Created on May 26, 2010

@author: michel
'''

import os
try:
    import json
except:
    import simplejson as json

CONFIG_DIR = os.path.join(os.environ['HOME'], '.mxdc')


def load_config(fname):
    config_file = os.path.join(CONFIG_DIR, fname)
    if os.access(config_file, os.R_OK):
        config = json.loads(file(config_file).read())
        return config

def save_config(fname, config):
    config_file = os.path.join(CONFIG_DIR, fname)
    if os.access(CONFIG_DIR, os.W_OK):
        f = open(config_file, 'w')
        json.dump(config, f)
        f.close()
        return True
    else:
        return False
        
    