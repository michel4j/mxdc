from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

(CASSETTE, CALIB_CASSETTE, PUCK_ADAPTER) = range(1,4)


class AutomounterContainer(object):
    def __init__(self, location, status_str=None):
        self.location = location
        self.samples = {}
        if status_str is not None:
            self.configure(status_str)
    
    def configure(self, status_str=None):
        if status_str is not None:
            self.container_type = int(status_str[0])
        else:
            return
        if self.container_type == PUCK_ADAPTER:
            self.keys = 'ABCD'
            self.indices = range(1,17)
        else:
            self.keys = 'ABCDEFJHIJKL'
            self.indices = range(1,9)
        count = 1
        for key in self.keys:
            for index in self.indices:
                id_str = '%s%d' % (key, index)
                if status_str is not None:
                    self.samples[id_str] = (status_str[count], '')
                else:
                    self.samples[id_str] = ('-', '')
                count +=1
                    
        
        
class Automounter(object):
    implements(IAutomounter)
    
    def __init__(self, pv_name):
        self.name = 'Sample Automounter'
        self._pv_name = pv_name
        self.FBK = ca.PV('%s:casette:fbk' % pv_name)
        self.container = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
        self.FBK.connect('changed', self._parse_status)
        
    def _parse_status(self, obj, val):
        fbstr = ''.join(val.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.container[k].configure(s)
            

if __name__ == '__main__':
    auto = Automounter('ROB1608-5-B10-01')
    sts = '31uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu---\
    -----------------------------11uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
    uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
    uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
    
    auto._parse_status(None, sts)
    print auto.container['L'].samples['A1']
    print auto.container['R'].samples['L8']
    print auto.container['M'].samples['A1']
    