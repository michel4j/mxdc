from bcm.utils import json
from datetime import date, datetime
import os
import atexit

try:
    import pynotify
    pynotify.init('MxDC')
    _NOTIFY_AVAILABLE = True
except:
    _NOTIFY_AVAILABLE = False


CONFIG_DIR = os.path.join(os.environ['HOME'], '.mxdc-%s' % os.environ['BCM_BEAMLINE'])
SESSION_CONFIG_FILE = 'session_config.json'
SESSION_INFO = {'path': os.environ['HOME']} # Default, update with get_session()



def save_session(session):
    session['date'] = date.today().isoformat()
    session['new'] = False
    return save_config(SESSION_CONFIG_FILE, session)

def load_config(fname):
    config_file = os.path.join(CONFIG_DIR, fname)
    if os.access(config_file, os.R_OK):
        config = json.loads(file(config_file).read())
        return config

def save_config(fname, config):
    if not os.path.exists(CONFIG_DIR) and os.access(os.environ['HOME'], os.W_OK):
        os.mkdir(CONFIG_DIR)

    config_file = os.path.join(CONFIG_DIR, fname)
    if os.access(CONFIG_DIR, os.W_OK):
        f = open(config_file, 'w')
        json.dump(config, f)
        f.close()
        return True
    else:
        return False

def get_session():
    config_file = os.path.join(CONFIG_DIR, SESSION_CONFIG_FILE)
    today = date.today()
    _path = os.path.join(os.environ['HOME'], "CLS%s-%s" % (os.environ['BCM_BEAMLINE'], today.strftime('%Y%b%d').upper()))
    session = {
        'path' : _path,
        'current_path': _path,
        'date' : today.isoformat(),
        'directories': [_path],
        'new' : True
    }
    if os.access(config_file, os.R_OK):
        prev_session = json.loads(file(config_file).read())
    else:
        prev_session = {'date': '1990-01-01'}
    
    prev_date = datetime.strptime(prev_session['date'], '%Y-%m-%d').date()
    if (today - prev_date).days > 7:  # Use new session if last was modified more than a week ago
        new_session = session
        if _NOTIFY_AVAILABLE:
            _notice = pynotify.Notification('New Session Directory', _path)
            try:
                _notice.show()
            except:
                pass

    else:
        new_session = prev_session
    if not os.path.exists(new_session['path']):
        os.makedirs(new_session['path'])
    SESSION_INFO.update(new_session)

atexit.register(save_session, SESSION_INFO)
