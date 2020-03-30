import unittest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mxdc import Device, Signal


class DevA(Device):
    class Signals:
        sig_int = Signal('sig-int', arg_types=(int,))
        sig_float = Signal('sig-float', arg_types=(float,))
        sig_str = Signal('sig-str', arg_types=(str,))
        sig_bool = Signal('sig-bool', arg_types=(bool,))


class DevB(DevA):
    class Signals:
        sig_multi = Signal('sig-multi', arg_types=(int, bool, float))


TEST_STATES = {
    'sig_int': 42,
    'sig_float': 12.5,
    'sig_bool': True,
    'sig_str': 'foobar',
    'sig_multi': (100, False, 3.1415)
}


class DeviceTestCase(unittest.TestCase):
    def setUp(self):
        self.dev_a = DevA()
        self.dev_b = DevB()
        self.dev_b.set_state(**TEST_STATES)

    def test_status_inheritance(self):
        sts_a = set(self.dev_a.get_states().keys())
        sts_b = set(self.dev_b.get_states().keys())

        self.assertTrue(
            sts_b >= sts_a,
            'Device signal inheritance problem {} -> {}'.format(repr(sts_a), repr(sts_b))
        )

    def test_status_values(self):
        for sig, value in TEST_STATES.items():
            self.assertTrue(
                self.dev_b.get_state(sig) == value,
                'Signal "{}" value {} failed: {}'.format(sig, repr(value), repr(self.dev_b.get_states()))
            )


if __name__ == '__main__':
    unittest.main()