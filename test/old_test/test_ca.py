'''
Created on Nov 30, 2009

@author: michel
'''
import unittest
import time
from bcm.protocol.ca import PV, flush
import subprocess
import os

pvdata = {'michel:testFloat': 20.5,
          'michel:testFloatA': [1,2,3,4,5,6,7,0,0,0],
          'michel:testDouble': 20.12345678901234,
          'michel:testDoubleA': [1.1,2.2,3.3,4.4,5.5,6.6,7.7,0,0,0],
          'michel:testIntA': [1,2,3,4,5,6,7,0,0,0],
          'michel:testLong': 65355653,
          'michel:testLongA': [1,2,3,4,5,6,7,0,0,0],
          'michel:testString': 'testing testing testing',
          'michel:testCharA': 'testing',
          'michel:testEnum': 2,
          }

class PVTest(unittest.TestCase):


    def setUp(self):
        os.chdir(os.path.join(os.environ['BCM_PATH'], 'bcm','test'))
        #self.ioc = subprocess.Popen(['softIoc','st.cmd'])
        # wait for ioc to run
        time.sleep(5)
        self._pv = {}
        for nm in pvdata.keys():
            self._pv[nm] = PV(nm)
        time.sleep(1)

    def tearDown(self):
        #self.ioc.terminate()
        pass


    def test_all(self):
        for nm, pv in self._pv.items():
            assert nm == pv.name
    
        for nm, pv in self._pv.items():
            pv.set(pvdata[nm])
        flush()
        for nm, pv in self._pv.items():
            print pv.value, ' = ', pvdata[nm]

        for nm, pv in self._pv.items():
            print pv.name, pv.value


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()