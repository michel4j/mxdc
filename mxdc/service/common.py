'''
Created on Oct 25, 2010

@author: michel
'''
import pwd
import os
from twisted.spread import pb


class BCMError(pb.Error):
    pass
    
class FileSystemError(BCMError):
    pass

class ConnectionRefused(BCMError):
    pass

class InvalidUser(BCMError):
    pass

class InvalidDirectory(BCMError):
    pass

class ServiceUnavailable(BCMError):
    pass

class BeamlineNotReady(BCMError):
    pass

class MountError(BCMError):
    pass

class CenteringError(BCMError):
    pass

def get_user_properties(user_name):
    try:
        pwdb = pwd.getpwnam(user_name)
        uid = pwdb.pw_uid
        gid = pwdb.pw_gid
        direc = pwdb.pw_dir
    except:
        raise InvalidUser('Unknown user `%s`' % user_name)
    return uid, gid, direc


def validate_directory(direc):
    if not os.path.exists(direc):
        raise InvalidDirectory('Directory `%s` does not exist.' % direc)
    if not os.access(dir, os.W_OK):
        raise InvalidDirectory('Permission denied for directory `%s`.' % direc)
    