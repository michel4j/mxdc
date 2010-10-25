'''
Created on Oct 25, 2010

@author: michel
'''
import pwd


class BCMError(Exception):
    pass
    
class FileSystemError(BCMError):
    pass

class InvalidUser(BCMError):
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
    except:
        raise InvalidUser('Unknown user `%s`' % user_name)
    return uid, gid

