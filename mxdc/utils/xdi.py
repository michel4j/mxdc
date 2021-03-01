# coding=utf-8


import collections
import gzip
import re
import sys
import textwrap
from datetime import datetime, tzinfo, timedelta
from io import StringIO

import numpy

VERSION = 1.0  # Specification version
NAMESPACES = [
    'facility', 'beamline', 'mono', 'detector', 'sample', 'scan', 'element', 'column'
]

SYMBOLS = [
    'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc',
    'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr',
    'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr',
    'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt',
    'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Bk',
    'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds', 'Rg', 'Cn', 'Uut', 'Fl', 'Uup', 'Lv',
    'Uus', 'Uuo'
]

EDGES = [
    'K', 'L', 'L1', 'L2', 'L3', 'M', 'M1', 'M2', 'M3', 'M4', 'M5', 'N', 'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7', 'O',
    'O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7'
]

REQUIRED_FIELDS = [
    'element.symbol', 'element.edge', 'mono.d_spacing'
]


def defaulted_namedtuple(typename, fields, defaults=None):
    """
    Create a namedtuple class with default values
    :param typename: Type name
    :param field_names: field names
    :param default_values: a dictionary of values to use as defaults otherwise None will be the default
    :return:
    """
    Type = collections.namedtuple(typename, fields)
    Type.__new__.__defaults__ = (None,) * len(Type._fields)
    if isinstance(defaults, collections.Mapping):
        prototype = Type(**defaults)
        Type.__new__.__defaults__ = tuple(prototype)
    return Type


# Values for fields
Field = defaulted_namedtuple('Field', ['value', 'units'], defaults={'units': None})


class OffsetTZ(tzinfo):
    """Fixed offset Timezone in hours and minutes east from UTC."""

    def __init__(self, name, **kwargs):
        """
        Create a Fixed offset timezone object
        :param name: Name of timezone
        :param kwargs: accepts the same keyworded arguments as datetime.timedelta
        """
        self.__offset = timedelta(**kwargs)
        self.__name = name

    def utcoffset(self, dt):
        return self.__offset

    def tzname(self, dt):
        return self.__name

    def dst(self, dt):
        return timedelta(0)


def isotime(text):
    patt = re.compile('(?P<date_text>[\d-]{8,10}[T ][\d:]{6,8}(?:\.\d+)?)Z?(?:(?P<sign>[+-])(?P<offset>\d{2}:\d{2}))?')
    m = patt.match(text)
    if m:
        info = m.groupdict()
        fmt = "%Y-%m-%dT%H:%M:%S" if ':' in info['date_text'] else "%Y%m%dT%H%M%S"
        offset_fmt = '%H:%M' if ':' in info['date_text'] else "%H%M"
        fmt += "" if not '.' in info['date_text'] else ".%f"
        dt = datetime.strptime(info['date_text'], fmt)
        if info['offset']:
            offset_dt = datetime.strptime(info['offset'], offset_fmt)
            sign = -1 if info['sign'] == '-' else 1
            timezone = OffsetTZ('Local', hours=sign * offset_dt.hour, minutes=sign * offset_dt.minute)
            dt = dt.replace(tzinfo=timezone)
        return dt
    else:
        raise ValueError('Invalid datetime format')


def symbol(text):
    assert text in SYMBOLS, 'Invalid Symbol'
    return text


def edge(text):
    assert text in EDGES, 'Invalid Symbol'
    return text


# Specification of tags used for verification and importing
TAGS = {
    'facility': [
        # tag, format, units
        ('name', str, None),
        ('energy', float, ['GeV', 'MeV']),
        ('current', float, ['mA', 'A']),
        ('xray_source', str, None),
    ],
    'beamline': [
        ('name', str, None),
        ('collimation', str, None),
        ('focusing', str, []),
        ('harmonic_rejection', str, None),
    ],
    'mono': [
        ('name', str, None),
        ('d_spacing', float, None),  # Å unit is implicit
    ],
    'detector': [
        ('i0', str, None),
        ('it', str, None),
        ('if', str, None),
        ('ir', str, None),
    ],
    'sample': [
        ('name', str, None),
        ('id', str, None),
        ('stoichiometry', str, None),
        ('prep', str, None),
        ('temperature', float, ['K', 'C']),
        ('experimenters', str, None),
    ],
    'scan': [
        ('start_time', isotime, None),
        ('end_time', isotime, None),
        ('edge_energy', float, ['eV', 'keV', '1/Å']),
        ('stoichiometry', str, None),
        ('prep', str, []),
        ('temperature', float, ['K', 'C']),
    ],
    'element': [
        ('symbol', symbol, None),
        ('edge', edge, None),
        ('reference', edge, None),
        ('ref_edge', edge, None),
    ],
    'column': [
        (int, str, []),  # empty unit list implies permissive units None implies no units
    ],

}


def memoize(f):
    """ Memoization decorator for functions taking one or more arguments. """

    class Memodict(object):
        def __init__(self, f):
            self.store = {}
            self.f = f

        def __call__(self, *args):
            if args in self.store:
                return self.store[args]
            else:
                ret = self.store[args] = self.f(*args)
                return ret

    return Memodict(f)


@memoize
def find_spec(namespace, tag):
    """
    Find the specifications for a given field
    :param namespace: The namespace to search
    :param tag: The tag to search within the namespace
    :return: [field name (str) or <int type>, field value format type, units (a list of strings) or None)]
    """
    specs = TAGS.get(namespace.lower(), [])
    spec = None
    # special case when a single spec is used for valued fields such as column numbers
    if len(specs) == 1 and not isinstance(specs[0][0], str):
        spec = specs[0]
    else:
        for item in specs:
            if item[0] == tag.lower():
                spec = item
    return spec

def format_field(field):
    suffix = '' if not field.units else ' {}'.format(field.units)
    if isinstance(field.value, datetime):
        return '{}{}'.format(field.value.isoformat(), suffix)
    else:
        return '{}{}'.format(field.value, suffix)
    

XDI_PATTERN = re.compile(
    '#\s*(?P<version_text>XDI/[^\n]*)\n'
    '(?P<header_text>(?:#\s*[^\n]*\n)+?)'
    '(?:#\s*/{3,}\n(?P<comments_text>.*?))?'
    '#\s*-{3,}\n'
    '#\s*(?P<columns_text>[^\n]*)\n'
    '(?P<data_text>.+)',
    re.DOTALL
)

HEADER_PATTERN = re.compile('#\s*(?P<namespace>[a-zA-Z]\w+).(?P<tag>[\w-]+):\s*(?P<text>[^\n]+)\s*')


class XDIData(object):
    def __init__(self, header=None, data=None, comments='', version=''):
        self.header = header or {}
        self.data = data
        self.comments = comments
        self.version = version

    def get_names(self):
        if self.data is not None:
            return self.data.dtype.names

    def __getitem__(self, key):
        if '.' in key:
            namespace, tag = key.lower().split('.')
            if not namespace in list(TAGS.keys()):
                namespace, tag = key.split('.') # preserve case for non-standard namespaces
            if namespace == 'column':
                tag = int(tag)
            return self.header[namespace][tag]
        else:
            return self.header[key.lower()]

    def __setitem__(self, key, entry):
        if isinstance(entry, dict) and not '.' in key:
            for k,v in list(entry.items()):
                self.__setitem__('{}.{}'.format(key, k), v)
        else:
            namespace, tag = key.lower().split('.')
            if isinstance(entry, tuple) and len(entry) == 2:
                value, unit = entry
            else:
                value, unit = entry, None

            spec = find_spec(namespace, tag)
            if spec:
                tag = tag if spec[0] != int else int(tag)
                name, fmt, units = spec
                if units is None:
                    unit = None
                elif units:
                    assert unit in units, 'Invalid Unit: {} for field {}.{}\n'.format(unit, namespace, tag)
                if fmt == isotime and isinstance(value, datetime):
                    value = value.isoformat()
                field = Field(value=value, units=unit)
            else :
                if namespace not in TAGS:
                    namespace = key.split('.')[0]  # preserve case for non-standard namespaces
                field = Field(value=value, units=unit)
            if namespace not in self.header:
                self.header[namespace] = {}
            self.header[namespace][tag] = field

    def save(self, filename):
        header_lines = ['# XDI/{} {}'.format(VERSION, self.version)] + [
            '{}.{}: {}'.format(
                namespace.islower() and namespace.capitalize() or namespace, tag,
                format_field(field),
            )
            for namespace, fields in list(self.header.items()) for tag, field in list(fields.items())
        ] + ['///'] + textwrap.wrap(self.comments) + ['---'] + [' '.join(self.data.dtype.names)]
        data_format = ''.join(['  {}'] * len(self.data.dtype.names))
        data_lines = [ data_format.format(*row) for row in self.data ]
        saver = gzip.open if filename.endswith('.gz') else open
        with saver(filename, 'wb') as handle:
            output = '\n# '.join(header_lines) + '\n' + '\n'.join(data_lines)
            handle.write(output.encode('utf8'))

    def parse(self, filename, permissive=False):
        opener = gzip.open if filename.endswith('.gz') else open
        with opener(filename, 'rb') as handle:
            raw = XDI_PATTERN.match(handle.read().decode('utf8')).groupdict()
        self.version = raw['version_text']

        self.header = {}
        header_rows = [m.groupdict() for m in HEADER_PATTERN.finditer(raw['header_text'])]
        for row in header_rows:
            namespace = row['namespace'].lower()
            tag = row['tag'].lower()
            spec = find_spec(namespace, tag)
            if spec:
                tag = tag if spec[0] != int else int(tag)
                name, fmt, units = spec
                if units is None:
                    field = Field(value=fmt(row['text'].strip()), units=None)
                else:
                    value_text, unit = re.match('([^\s]+)\s*(.+)?', row['text']).groups()
                    try:
                        value = fmt(value_text)
                    except ValueError as e:
                        sys.stderr.write('Invalid Value: {} for field {}.{}\n'.format(value_text, namespace, tag))
                        continue
                    if units and unit not in units:
                        sys.stderr.write('Invalid Unit: {} for field {}.{}\n'.format(unit, namespace, tag))
                        continue
                    field = Field(value=value, units=unit)
            else:
                if not namespace in TAGS:
                    namespace = row['namespace']  # preserve capitalization for non-standard namespaces
                field = Field(value=row['text'].strip())
            if namespace not in self.header:
                self.header[namespace] = {}
            self.header[namespace][tag] = field

        columns = list(dict(sorted(self.header['column'].items())).values())
        header_columns = [col.value for col in columns]

        self.comments = '' if not raw['comments_text'] else ' '.join(raw['comments_text'].replace('#', '').split())
        data_columns = raw['columns_text'].split()

        if data_columns != header_columns:
            sys.stderr.write('Error! Data columns do not match header: {} vs {}\n'.format(data_columns, header_columns))
            return

        missing = {
            field: field.split('.')[1] not in self.header.get(field.split('.')[0], {})
            for field in REQUIRED_FIELDS
        }
        if not permissive and any(missing.values()):
            sys.stderr.write('Required fields missing: {}\n'.format([key for key, value in list(missing.items()) if value]))

        self.data = numpy.genfromtxt(StringIO('{}'.format(raw['data_text'])), dtype=None, names=data_columns, deletechars='')


def read_xdi(filename):
    obj = XDIData()
    obj.parse(filename)
    return obj
