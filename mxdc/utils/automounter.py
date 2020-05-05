

import cairo
import numpy


class Port(object):
    EMPTY, UNKNOWN, GOOD, MOUNTED, BAD = list(range(5))


PortColors = {
    Port.EMPTY: {'red': 0.0, 'green': 0.0, 'blue': 0.0, 'alpha': 0.5},
    Port.GOOD: {'red': 0.5, 'green': 0.75, 'blue': 0.8, 'alpha': 0.8},
    Port.UNKNOWN: {'red': 1.0, 'green': 1.0, 'blue': 1.0, 'alpha': 0.5},
    Port.MOUNTED: {'red': 0.75, 'green': 0.5, 'blue': 1.0, 'alpha': 1},
    Port.BAD: {'red': 0.9, 'green': 0.5, 'blue': 0.5, 'alpha': 0.6},
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
        return {key: val for key, val in list(cls.plugins.items())}

    def get(cls, key):
        return cls.plugins.get(key)


class Container(object, metaclass=ContainerMeta):
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

                state = ports.get(port, Port.UNKNOWN)
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
        for label, (lx, ly) in list(self.labels().items()):
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


class Plate(Container):
    PIN = 1/24.
    WIDTH = 7/31.
    HEIGHT = 5/31.
    SHAPE = 'rectangle'
    COORDS = numpy.array([(i/12., 1-j/16. + ((j%2)-0.5)/64.) for x in range(8 * 24) for j, i in [divmod(x, 12)]])
    NAMES = tuple('{}{}'.format(chr(ord('A') + row//2), (col)+((row%2)*12) + 1) for i in range(8 * 24) for row, col in [divmod(i, 12)])


