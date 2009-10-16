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
    'u': PORT_UNKNOWN , 
    'm': PORT_MOUNTED, 
    'j': PORT_JAMMED,
    'b': PORT_EMPTY,
    '-': PORT_NONE }

STATE_NEED_STRINGS = {
1: 'inspect:staff',
2: 'reset',
4: 'calib:toolset',
8: 'calib:cassette',
16: 'calib:goniometer',
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

