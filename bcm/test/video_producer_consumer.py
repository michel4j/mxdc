from bcm.device.video import CACamera
from bcm.device.motor import CLSMotor
from twisted.internet import protocol, reactor, defer, utils, interfaces, error
from zope.interface import implements
import gtk
import gobject

class VideoSource(object):
    """A push producer that sends video frames to a consumer.
    """
    implements(interfaces.IPushProducer)
    deferred = None

    def __init__(self, camera, maxfps=10.0):
        self.camera = camera
        self.consumers = []
        self.maxfps = 10.0

    def addConsumer(self, consumer):
        consumer.registerProducer(self, True)
        self.consumers.append(consumer)
    
    def checkWork(self):
        img = self.camera.get_frame()
        img = img.convert('RGB')
        w, h = img.size
        pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
            False, 8, w, h, 3 * w)
        for consumer in self.consumers:
            consumer.write(pixbuf)
        self._call_id = reactor.callLater(1.0/self.maxfps, self.checkWork)
        
    def resumeProducing(self):
        self.checkWork()
                              
    def pauseProducing(self):
        self._call_id.cancel()

    def stopProducing(self):
        if self.deferred:
            self.deferred.errback(Exception("Consumer asked us to stop producing"))
            self.deferred = None


class VideoSink(object):
    implements(interfaces.IConsumer)
    
    def __init__(self):
        pass
        
    def registerProducer(self, producer, streaming):
        self.producer = producer
        assert streaming
        self.producer.resumeProducing()

    def unregisterProducer(self):
        self.producer = None

    def write(self, frame):
        print frame, 'received'

if __name__ == '__main__':
    sample_zoom = CLSMotor('SMTR16083I1021:mm')
    video = CACamera('CAM1608-001:data', sample_zoom)
    cons = VideoSink()
    prod = VideoSource(video)
    prod.addConsumer(cons)
    reactor.run()
