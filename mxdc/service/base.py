from mxdc.device.base import BaseDevice

class BaseService(BaseDevice):
    
    def __init__(self):
        BaseDevice.__init__(self)
        self.name = self.__class__.__name__ + ' Service'
