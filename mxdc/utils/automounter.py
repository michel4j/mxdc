from __future__ import division

import cairo
import numpy


class Port(object):
    EMPTY, UNKNOWN, GOOD, MOUNTED, BAD = range(5)


PortColors = {
    Port.EMPTY: {'red': 0.0, 'green': 0.0, 'blue': 0.0, 'alpha': 0.5},
    Port.GOOD: {'red': 0.5, 'green': 0.75, 'blue': 0.8, 'alpha': 0.8},
    Port.UNKNOWN: {'red': 1.0, 'green': 1.0, 'blue': 1.0, 'alpha': 0.8},
    Port.MOUNTED: {'red': 0.5, 'green': .2, 'blue': 0.5, 'alpha': 0.8},
    Port.BAD: {'red': 0.9, 'green': 0.7, 'blue': 0.7, 'alpha': 0.8},
}


def basket_coords():
    polar = numpy.array([
        (3.14159265, 0.75),
        (2.57039399, 0.75),
        (1.99919533, 0.75),
        (1.42799666, 0.75),
        (0.856798, 0.75),
        (0.28559933, 0.75),
        (-0.28559933, 0.75),
        (-0.856798, 0.75),
        (-1.42799666, 0.75),
        (-1.99919533, 0.75)
    ])
    return numpy.array((polar[:, 1] * numpy.cos(polar[:, 0]), polar[:, 1] * numpy.sin(polar[:, 0]))).T


def puck_coords():
    polar = numpy.array([
        (3.14159265, 0.36),
        (1.88495559, 0.36),
        (0.62831853, 0.36),
        (-0.62831853, 0.36),
        (-1.88495559, 0.36),
        (3.14159265, 0.75),
        (2.57039399, 0.75),
        (1.99919533, 0.75),
        (1.42799666, 0.75),
        (0.856798, 0.75),
        (0.28559933, 0.75),
        (-0.28559933, 0.75),
        (-0.856798, 0.75),
        (-1.42799666, 0.75),
        (-1.99919533, 0.75),
        (-2.57039399, 0.75)
    ])
    return numpy.array((0.5 * polar[:, 1] * numpy.sin(polar[:, 0]), 0.5 * polar[:, 1] * numpy.cos(polar[:, 0]))).T


def text_color(color, alpha):
    br = 0.241 * color['red'] ** 2 + 0.691 * color['green'] ** 2 + 0.068 * color['blue'] ** 2
    return (0.0, 0.0, 0.0, alpha) if br > 0.5*alpha else  (1.0, 1.0, 1.0, alpha)


class ContainerMeta(type):
    def __init__(cls, *args, **kwargs):
        super(ContainerMeta, cls).__init__(*args, **kwargs)
        cls.key = cls.__name__.lower()

        if not hasattr(cls, 'plugins'):
            cls.plugins = {}
        else:
            cls.plugins[cls.key] = cls

    def get_all(cls, *args, **kwargs):
        return {key: val for key, val in cls.plugins.items()}

    def get(cls, key):
        return cls.plugins.get(key)


class Container(object):
    __metaclass__ = ContainerMeta
    PIN = 12 / 31.
    WIDTH = 1 / 12.
    HEIGHT = 1 / 12.
    CIRCLE = False
    NAMES = ()
    COORDS = ()

    def __init__(self, location, cx, cy):
        self.cx = cx
        self.cy = cy
        self.cxy = numpy.array((cx, cy))
        self.pin_size = self.PIN * self.WIDTH
        self.loc = location

    def draw(self, cr, ports, containers):
        cr.save()
        cr.translate(self.cx, self.cy)
        cr.scale(self.WIDTH, self.WIDTH)
        xscale, yscale = cr.device_to_user_distance(1, 1)
        cr.set_font_size(10 * xscale)
        cr.set_line_width(1 * xscale)

        # Draw outline of container
        if self.CIRCLE:
            cr.arc(0, 0, 0.5, 0, 2.0 * 3.14)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.15)
            cr.fill()
            cr.arc(0, 0, 0.5, 0, 2.0 * 3.14)
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.stroke()
        else:
            cr.rectangle(-0.5, -0.5 * self.HEIGHT / self.WIDTH, 1, self.HEIGHT / self.WIDTH)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.15)
            cr.fill()
            cr.rectangle(-0.5, -0.5 * self.HEIGHT / self.WIDTH, 1, self.HEIGHT / self.WIDTH)
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.stroke()

        # draw pins for owner or admin
        if self.loc in containers:
            for i, pin in enumerate(self.NAMES):
                px, py = self.COORDS[i]
                port = '{}{}'.format(self.loc, pin)

                state = ports.get(port)
                if state is None: continue
                color = PortColors.get(state)

                cr.set_source_rgba(color['red'], color['green'], color['blue'], color['alpha'])
                cr.arc(px, py, self.PIN / 2., 0, 2.0 * 3.14)
                cr.fill()
                cr.arc(px, py, self.PIN / 2., 0, 2.0 * 3.14)
                cr.set_source_rgba(0.5, 0.5, 0.5, 0.5)
                cr.stroke()

                xb, yb, w, h = cr.text_extents(pin)[:4]
                cr.move_to(px - w / 2. - xb, py - h / 2. - yb)
                cr.set_source_rgba(*text_color(color, color['alpha']))
                cr.show_text(pin)
                cr.stroke()

        # draw labels
        cr.set_source_rgba(0.0, 0.375, 0.75, 1.0)
        cr.select_font_face('Cantarell', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        for label, (lx, ly) in self.labels().items():
            xb, yb, w, h = cr.text_extents(label)[:4]
            cr.move_to(lx - w / 2. - xb, ly - h / 2. - yb)
            cr.show_text(label)
            cr.stroke()

        cr.restore()

    def name(self, i):
        return self.NAMES[i]

    def labels(self):
        return {}

    def get_port(self, x, y):
        mxy = numpy.array((x, y))
        bxy = (mxy - self.cxy) / self.WIDTH
        if (numpy.abs(bxy) > 0.5).sum():
            return
        else:
            for i, pin in enumerate(self.COORDS):
                if numpy.hypot(*(bxy - pin)) < 0.5 * self.PIN:
                    return '{}{}'.format(self.loc, self.NAMES[i])


class Puck(Container):
    PIN = 6 / 31.
    WIDTH = 2 / 12.
    HEIGHT = 2 / 12.
    CIRCLE = True
    COORDS = puck_coords()
    NAMES = tuple('{}'.format(i + 1) for i in range(16))

    def labels(self):
        return {self.loc: (0, 0)}


class Basket(Container):
    WIDTH = 1 / 12.
    HEIGHT = 1 / 12.
    CIRCLE = True
    COORDS = basket_coords()
    NAMES = tuple('{}'.format(i + 1) for i in range(10))

    def labels(self):
        return {self.loc: (0, 0)}


class Cassette(Container):
    PIN = 1 / 12.
    WIDTH = 14 / 31.
    HEIGHT = 10 / 31.
    SHAPE = 'rectangle'
    COORDS = numpy.array([((i - 5.5) / 12.2, (j - 3.5) / 12.2) for x in range(8 * 12) for i, j in [divmod(x, 8)]])
    NAMES = tuple('{}{}'.format(chr(ord('A') + col), row + 1) for i in range(8 * 12) for col, row in [divmod(i, 8)])

    def labels(self):
        return {self.loc: (0, -5 / 12.)}


SAM_DEWAR = {
    # Puck Adapters
    'LA': Puck('LA', 0.25 - 1 / 12., 0.25 - 1 / 12.),
    'LB': Puck('LB', 0.25 - 1 / 12., 0.25 + 1 / 12.),
    'LC': Puck('LC', 0.25 + 1 / 12., 0.25 - 1 / 12.),
    'LD': Puck('LD', 0.25 + 1 / 12., 0.25 + 1 / 12.),

    'MA': Puck('MA', 0.5 - 1 / 12., 0.75 - 1 / 12.),
    'MB': Puck('MB', 0.5 - 1 / 12., 0.75 + 1 / 12.),
    'MC': Puck('MC', 0.5 + 1 / 12., 0.75 - 1 / 12.),
    'MD': Puck('MD', 0.5 + 1 / 12., 0.75 + 1 / 12.),

    'RA': Puck('RA', 0.75 - 1 / 12, 0.25 - 1 / 12.),
    'RB': Puck('RB', 0.75 - 1 / 12, 0.25 + 1 / 12.),
    'RC': Puck('RC', 0.75 + 1 / 12, 0.25 - 1 / 12.),
    'RD': Puck('RD', 0.75 + 1 / 12, 0.25 + 1 / 12.),

    # Cassettes
    'L': Cassette('L', 0.25, 0.25),
    'M': Cassette('M', 0.50, 0.75),
    'R': Cassette('R', 0.75, 0.25)

}

ISARA_DEWAR = {
    '1A': Puck('1A', 0.1667, 1.75 / 13.),
    '2A': Puck('2A', 0.3333, 1.75 / 13.),
    '3A': Puck('3A', 0.5, 1.75 / 13.),
    '4A': Puck('4A', 0.6667, 1.75 / 13.),
    '5A': Puck('5A', 0.8333, 1.75 / 13.),

    '1B': Puck('1B', 0.0833, 3.65 / 13.),
    '2B': Puck('2B', 0.25, 3.65 / 13.),
    '3B': Puck('3B', 0.4167, 3.65 / 13),
    '4B': Puck('4B', 0.5833, 3.65 / 13),
    '5B': Puck('5B', 0.75, 3.65 / 13),
    '6B': Puck('6B', 0.9167, 3.65 / 13),

    '1C': Puck('1C', 0.1667, 5.55 / 13),
    '2C': Puck('2C', 0.3333, 5.55 / 13),
    '3C': Puck('3C', 0.5, 5.55 / 13),
    '4C': Puck('4C', 0.6667, 5.55 / 13),
    '5C': Puck('5C', 0.8333, 5.55 / 13),

    '1D': Puck('1D', 0.0833, 7.45 / 13.),
    '2D': Puck('2D', 0.25, 7.45 / 13),
    '3D': Puck('3D', 0.4167, 7.45 / 13),
    '4D': Puck('4D', 0.5833, 7.45 / 13),
    '5D': Puck('5D', 0.75, 7.45 / 13),
    '6D': Puck('6D', 0.9167, 7.45 / 13),

    '1E': Puck('1E', 0.1667, 9.35 / 13),
    '2E': Puck('2E', 0.3333, 9.35 / 13),
    '3E': Puck('3E', 0.5, 9.35 / 13),
    '4E': Puck('4E', 0.6667, 9.35 / 13),
    '5E': Puck('5E', 0.8333, 9.35 / 13),

    '1F': Puck('1F', 0.4167, 11.25 / 13),
    '2F': Puck('2F', 0.5833, 11.25 / 13),

}

CATS_DEWAR = {
    '1A': Basket('1A', 0.1667, 0.0833),
    '1B': Basket('1B', 0.0833, 0.2292),
    '1C': Basket('1C', 0.25, 0.2292),
    '2A': Basket('2A', 0.5, 0.6667),
    '2B': Basket('2B', 0.4167, 0.8125),
    '2C': Basket('2C', 0.5833, 0.8125),
    '3A': Basket('3A', 0.8333, 0.0833),
    '3B': Basket('3B', 0.75, 0.2292),
    '3C': Basket('3C', 0.9167, 0.2292),
}
