from zope.interface import implements
from bcm.interfaces.cameras import ICamera
from bcm.protocols.ca import PV
import gobject

import numpy
from scipy.misc import toimage, fromimage
import Image, ImageOps, urllib, cStringIO
import httplib

class CameraBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
        self.frame = None
        self.camera_on = False
        self.controller = None

    def do_changed(self):
        self.update()
        
    def signal_change(self, obj, val=None):
        gobject.idle_add(self.emit,'changed')
        return True
    
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)

    def get_frame(self):
        return self.frame
    
    def update(self, obj=None, force=None):
        return True
    
    def save(self, filename):
        if self.frame is None:
            self.log('No image available to save')
        else:
            try:
                img = ImageOps.autocontrast(self.frame)
                img.save(filename)
            except:
                self.log('Could not save image: %s' % filename)
    
    def is_on(self):
        return self.camera_on
    
    def stop(self):
        self.camera_on = False
        
    def start(self):
        self.update(force=True)
        self.camera_on = True
                 
class CameraSim(CameraBase):
    def __init__(self):
        CameraBase.__init__(self)
        self._fsource = open('/dev/urandom','rb')
        self._packet_size = 307200
        gobject.timeout_add(50, self.signal_change)
    
    def __del__(self):
        self._fsource.close()
        self._data = None 
    
    def update(self, obj=None, force=False):
        if self.is_on() or force:
            self._data = self._fsource.read(307200)
            self.frame = toimage(numpy.fromstring(self._data, 'B').reshape(480,640))
                   

class Camera(CameraBase):
    def __init__(self, pv_name):
        CameraBase.__init__(self)
        self.cam = PV(pv_name)
        self._data = None
        self.cam.connect('changed', self.signal_change)
    
    def update(self, obj=None, force=False):
        if self.is_on() or force:
            self._data = self.cam.get()
            self.frame = toimage(numpy.fromstring(self._data, 'B').reshape(480,640))

                                
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
    def __init__(self,hostname):
        CameraBase.__init__(self)
        self.url = 'http://%s/jpg/image.jpg' % hostname
        self.controller = AxisController(hostname)
        gobject.timeout_add(100, self.signal_change)
        
    def update(self, obj=None,force=False):
        if self.is_on() or force:
            img_file = urllib.urlopen(self.url)
            img_str = cStringIO.StringIO(img_file.read())
            self.frame = Image.open(img_str)


gobject.type_register(CameraBase)

        
