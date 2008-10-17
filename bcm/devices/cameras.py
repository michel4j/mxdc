from zope.interface import implements
from bcm.interfaces.cameras import ICamera
from bcm.protocols.ca import PV
import time
import gobject

import numpy
from scipy.misc import toimage, fromimage
import Image, ImageOps, urllib, cStringIO
import httplib


class CameraBase(gobject.GObject):
    __gsignals__ =  { 
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }
    def __init__(self, name='Video'):
        gobject.GObject.__init__(self)
        self.frame = None
        self.camera_on = False
        self.controller = None
        self.name = name
            
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)

    def get_frame(self):
        return self.frame
    
    def update(self, obj=None, force=None):
        return True
    
    def save(self, filename):
        if self.frame is None:
            self._log('No image available to save')
            result = False
        else:
            try:
                img = ImageOps.autocontrast(self.get_frame())
                img.save(filename)
                result = filename
            except:
                self._log('Could not save image: %s' % filename)
                result = False
        return result

    def get_name(self):
        return self.name
    
    
                 
class CameraSim(CameraBase):
    def __init__(self,name='Video'):
        CameraBase.__init__(self,name)
        self._fsource = open('/dev/urandom','rb')
        self._packet_size = 307200
        self.name = name
        self.update()
        #gobject.timeout_add(100, self.update)
    
    def __del__(self):
        self._fsource.close()
    
    def update(self, obj=None):
        data = self._fsource.read(self._packet_size)
        self.frame = toimage(numpy.fromstring(data, 'B').reshape(480,640))
        self.size = self.frame.size
        return True
                   
    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None

class Camera(CameraBase):
    def __init__(self, pv_name, name='Video'):
        CameraBase.__init__(self,name)
        self._fsource = open('/dev/urandom','rb')
        self.cam = PV(pv_name)
        self._packet_size = 307200
        self.update()
    
    def __del__(self):
        self._fsource.close()


    def update(self, obj=None, arg=None):
        if self.cam.is_connected():
            data = self.cam.get()
            while len(data) != self._packet_size:
                data = self.cam.get()
        else:
            data = self._fsource.read(self._packet_size)

        self.frame = toimage(numpy.fromstring(data, 'B').reshape(480,640))
        self.size = self.frame.size
        return True

    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None


                                
class AxisController:
    def __init__(self,hostname):
        self.server = httplib.HTTPConnection(hostname)
        self.rzoom = 0
        
    def zoom(self,value):
        self.server.connect()
        command = "/axis-cgi/com/ptz.cgi?rzoom=%s" % value
        result = self.server.request("GET", command)
        self.rzoom -= value
        self.server.close()
        return

    def center(self, x, y):
        self.server.connect()
        command = "/axis-cgi/com/ptz.cgi?center=%d,%d" % (x, y)
        result = self.server.request("GET", command)
        self.server.close()
        return
    
    def goto(self, position):
        self.server.connect()
        position = urllib.quote_plus(position)
        command = "/axis-cgi/com/ptz.cgi?gotoserverpresetname=%s" % position
        result = self.server.request("GET", command)
        self.rzoom = 0
        self.server.close()
        return

class AxisCamera(CameraBase):
    def __init__(self,hostname, name='Video'):
        CameraBase.__init__(self,name)
        self.url = 'http://%s/jpg/image.jpg' % hostname
        self.controller = AxisController(hostname)
        self.size = (704,480)
        self._last_frame = time.time()
        self.update()

    def _get_image(self):
            f = urllib.urlopen(self.url)
            f_str = cStringIO.StringIO(f.read())
            return Image.open(f_str)

    def update(self, obj=None):
        if time.time() - self._last_frame < 0.1:
            return True
        try:
            self.frame = self._get_image()
            self._last_frame = time.time()
        except:
            self._log('Error fetching frame')
            return False
        return True


    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None
        
gobject.type_register(CameraBase)
