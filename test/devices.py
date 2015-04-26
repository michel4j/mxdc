import unittest

class BaseDeviceTestCase(unittest.TestCase):
    def setUp(self):
        from mxdc.device.base import BaseDevice
        self.device = BaseDevice()
    
    def test_get_status(self):
        sts = self.device.get_state()
        expected = set(['active','busy','error','message'])
        observed = set(sts.keys())
        self.assertEqual(expected,  observed,
                         'return value of get_status() is inappropriate. expecting %s, got %s' % (expected, observed))
        self.assertTrue((sts['active'] in [True, False]), 'returned "active" status is not boolean')
        self.assertTrue((sts['busy'] in [True, False]), 'returned "busy" status is not boolean')
        self.assertEqual(len(sts['error']), 2, 'returned "error" must be a sequence of two entries')
        