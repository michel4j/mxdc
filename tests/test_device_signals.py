import pytest
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


@pytest.fixture
def setup_devices():
    dev_a = DevA()
    dev_b = DevB()
    dev_b.set_state(**TEST_STATES)
    return dev_a, dev_b


def test_status_inheritance(setup_devices):
    dev_a, dev_b = setup_devices
    sts_a = set(dev_a.get_states().keys())
    sts_b = set(dev_b.get_states().keys())

    assert sts_b >= sts_a, f'Device signal inheritance problem {repr(sts_a)} -> {repr(sts_b)}'


def test_status_values(setup_devices):
    dev_a, dev_b = setup_devices
    for sig, value in TEST_STATES.items():
        assert dev_b.get_state(sig) == value, f'Signal "{sig}" value {repr(value)} failed: {repr(dev_b.get_states())}'
