from __future__ import division
import numpy

(CONTAINER_EMPTY,
 CONTAINER_CASSETTE,
 CONTAINER_CALIB_CASSETTE,
 CONTAINER_PUCK_ADAPTER,
 CONTAINER_UNKNOWN,
 CONTAINER_NONE) = range(6)

(PORT_EMPTY,
 PORT_GOOD,
 PORT_UNKNOWN,
 PORT_MOUNTED,
 PORT_JAMMED,
 PORT_NONE) = range(6)

PORT_STATE_TABLE = {
    '0': PORT_EMPTY,
    '1': PORT_GOOD,
    'u': PORT_UNKNOWN,
    'm': PORT_MOUNTED,
    'j': PORT_JAMMED,
    'b': PORT_EMPTY,
    '-': PORT_NONE}

STATE_NEED_STRINGS = {
    1: 'inspect:staff',
    2: 'reset',
    4: 'calib:toolset',
    8: 'calib:ports',
    16: 'calib:gonio',
    32: 'calib:initial',
    64: 'action:user',
}

STATE_REASON_STRINGS = {
    256: 'emergency stop',
    512: 'safeguard latched',
    1024: 'not at home',
    4096: 'lid jam',
    8192: 'gripper jam',
    16384: 'magnet missing',
    65536: 'init error',
    131072: 'toolset error',
    262144: 'LN2 Level error',
    1048576: 'cassette seating',
    2097152: 'pin lost',
    4194304: 'wrong state',
    16777216: 'port occupied',
    33554432: 'internal abort',
    67108864: 'gonio unreachable',
}


def puck():
    # first pair is center, last pair is label position, rest are pins
    angles = [0, 3.14159265, 1.88495559, 0.62831853, -0.62831853, -1.88495559,
              3.14159265, 2.57039399, 1.99919533, 1.42799666, 0.856798,
              0.28559933, -0.28559933, -0.856798, -1.42799666, -1.99919533,
              -2.57039399, 0]
    radii = [0, 0.36, 0.36, 0.36, 0.36, 0.36, 0.75, 0.75, 0.75, 0.75,
             0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0]
    return numpy.array([radii * numpy.cos(angles), radii * numpy.sin(angles)]).T * 1 / 12.


def cassette():
    # first pair is center, last pair is label position, rest are pins
    y = [0, -7, -5, -3, -1, 1, 3, 5, 7, -9]
    x = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    return numpy.array((x, y)).T * 1 / 52.


def basket():
    # first pair is center, last pair is label position, rest are pins
    angles = [0, 3.14159265, 2.57039399, 1.99919533, 1.42799666, 0.856798, 0.28559933, -0.28559933, -0.856798,
              -1.42799666, -1.99919533, 0]
    radii = [0, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0]
    return numpy.array((radii * numpy.cos(angles), radii * numpy.sin(angles))).T * 1 / 12.


ContainerCoords = {
    'puck': puck(),
    'basket': basket(),
    'cassette': cassette(),
}

SAM_LAYOUTS = {
    ('MA', 'puck'): (0.4167, 0.6008),
    ('MB', 'puck'): (0.3333, 0.7467),
    ('MC', 'puck'): (0.5833, 0.6008),
    ('MD', 'puck'): (0.5000, 0.7467),

    ('LA', 'puck'): (0.0833, 0.1492),
    ('LB', 'puck'): (0.1667, 0.2950),
    ('LC', 'puck'): (0.2500, 0.1492),
    ('LD', 'puck'): (0.3333, 0.2950),

    ('RA', 'puck'): (0.7500, 0.1492),
    ('RB', 'puck'): (0.6667, 0.2950),
    ('RC', 'puck'): (0.9167, 0.1492),
    ('RD', 'puck'): (0.8333, 0.2950),

    ('MA', 'cassette'): (0.3053, 0.6731),
    ('MB', 'cassette'): (0.3389, 0.6923),
    ('MC', 'cassette'): (0.3726, 0.6731),
    ('MD', 'cassette'): (0.4062, 0.6923),
    ('ME', 'cassette'): (0.4399, 0.6731),
    ('MF', 'cassette'): (0.4736, 0.6923),
    ('MG', 'cassette'): (0.5072, 0.6731),
    ('MH', 'cassette'): (0.5409, 0.6923),
    ('MI', 'cassette'): (0.5745, 0.6731),
    ('MJ', 'cassette'): (0.6082, 0.6923),
    ('MK', 'cassette'): (0.6418, 0.6731),
    ('ML', 'cassette'): (0.6755, 0.6923),

    ('LA', 'cassette'): (0.0192, 0.1923),
    ('LB', 'cassette'): (0.0529, 0.2115),
    ('LC', 'cassette'): (0.0865, 0.1923),
    ('LD', 'cassette'): (0.1202, 0.2115),
    ('LE', 'cassette'): (0.1538, 0.1923),
    ('LF', 'cassette'): (0.1875, 0.2115),
    ('LG', 'cassette'): (0.2212, 0.1923),
    ('LH', 'cassette'): (0.2548, 0.2115),
    ('LI', 'cassette'): (0.2885, 0.1923),
    ('LJ', 'cassette'): (0.3221, 0.2115),
    ('LK', 'cassette'): (0.3558, 0.1923),
    ('LL', 'cassette'): (0.3894, 0.2115),

    ('RA', 'cassette'): (0.6106, 0.1923),
    ('RB', 'cassette'): (0.6442, 0.2115),
    ('RC', 'cassette'): (0.6779, 0.1923),
    ('RD', 'cassette'): (0.7115, 0.2115),
    ('RE', 'cassette'): (0.7452, 0.1923),
    ('RF', 'cassette'): (0.7788, 0.2115),
    ('RG', 'cassette'): (0.8125, 0.1923),
    ('RH', 'cassette'): (0.8462, 0.2115),
    ('RI', 'cassette'): (0.8798, 0.1923),
    ('RJ', 'cassette'): (0.9135, 0.2115),
    ('RK', 'cassette'): (0.9471, 0.1923),
    ('RL', 'cassette'): (0.9808, 0.2115),

}

ISARA_LAYOUTS = {
    ('1F', 'puck'): (0.4167, 0.8125),
    ('1A', 'puck'): (0.1667, 0.0833),
    ('5E', 'puck'): (0.8333, 0.6667),
    ('1C', 'puck'): (0.1667, 0.3750),
    ('1B', 'puck'): (0.0833, 0.2292),
    ('1E', 'puck'): (0.1667, 0.6667),
    ('1D', 'puck'): (0.0833, 0.5208),
    ('3B', 'puck'): (0.4167, 0.2292),
    ('3C', 'puck'): (0.5000, 0.3750),
    ('5D', 'puck'): (0.7500, 0.5208),
    ('3A', 'puck'): (0.5000, 0.0833),
    ('5A', 'puck'): (0.8333, 0.0833),
    ('5C', 'puck'): (0.8333, 0.3750),
    ('3D', 'puck'): (0.4167, 0.5208),
    ('3E', 'puck'): (0.5000, 0.6667),
    ('5B', 'puck'): (0.7500, 0.2292),
    ('2D', 'puck'): (0.2500, 0.5208),
    ('2E', 'puck'): (0.3333, 0.6667),
    ('2F', 'puck'): (0.5833, 0.8125),
    ('2A', 'puck'): (0.3333, 0.0833),
    ('2B', 'puck'): (0.2500, 0.2292),
    ('2C', 'puck'): (0.3333, 0.3750),
    ('4D', 'puck'): (0.5833, 0.5208),
    ('4E', 'puck'): (0.6667, 0.6667),
    ('4B', 'puck'): (0.5833, 0.2292),
    ('4C', 'puck'): (0.6667, 0.3750),
    ('4A', 'puck'): (0.6667, 0.0833),
    ('6B', 'puck'): (0.9167, 0.2292),
    ('6D', 'puck'): (0.9167, 0.5208),
}

CATS_LAYOUTS = {
    ('1A', 'basket'): (0.1667, 0.0833),
    ('1C', 'basket'): (0.2500, 0.2292),
    ('1B', 'basket'): (0.0833, 0.2292),
    ('2A', 'basket'): (0.5000, 0.6667),
    ('2B', 'basket'): (0.4167, 0.8125),
    ('2C', 'basket'): (0.5833, 0.8125),
    ('3C', 'basket'): (0.9167, 0.2292),
    ('3B', 'basket'): (0.7500, 0.2292),
    ('3A', 'basket'): (0.8333, 0.0833),
}
