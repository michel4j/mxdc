import unittest
import time
from bcm.device.counter import Counter


class CounterTestCase(unittest.TestCase):
    def setUp(self):
        self.counter = Counter('BL08ID1:XrayBpm:sum')

    def tearDown(self):
        del self.counter
        self.counter = None
   
    def testInterface(self):
        self.failUnless(hasattr(self.counter,'name'),'"name" attribute required.')
        self.failUnless(hasattr(self.counter,'value'),'"value" attribute required.')
        self.failUnless(hasattr(self.counter,'count'),'"count()" attribute required.')
    
    def testValue(self):
        v = self.counter.value.get()
        
    def testCounting(self):
        t0 = time.time()
        self.counter.count(0.1)
        t1 = time.time()
        oh = (t1-t0)
        self.failUnless(1.15 * 0.1 > oh, 'Counting overhead (%f %%) is more than 15 %%' % (oh*100) )