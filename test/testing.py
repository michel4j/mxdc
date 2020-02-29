import random
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib, Gtk
import time


def _make_tuple(value_type):
    """
    Convert a value_type into a typle of value_types
    @param value_type: value type
    @return: tuple of value types
    """
    if isinstance(value_type, (tuple, list)):
        return value_type
    elif value_type in (bool, object, str, int, float):
        return value_type,


def _make_signal_name(name):
    """
    Format a signal name from an attribute name
    @param name: attribute name
    @return: signal name
    """
    return name.replace('_', '-')


class Signal(object):
    def __init__(self, name, types, first=False, last=False):
        self.name = name
        self.types = _make_tuple(types)
        self.first = first
        self.last = last

    def attrs(self):
        if self.first:
            flag = GObject.SignalFlags.RUN_FIRST
        elif self.last:
            flag = GObject.SignalFlags.RUN_LAST
        else:
            flag = GObject.SignalFlags.ACTION
        return flag, None, self.types


class SignalsMeta(type(GObject.GObject)):
    def __new__(cls, class_name, superclasses, attributes):
        signals = attributes.pop('Signals', None)

        # generate and update gsignals
        if signals:
            signal_types = {
                name: signal for name, signal in signals.__dict__.items() if isinstance(signal, Signal)
            }
            if '__signal_types__' in attributes:
                attributes['__signal_types__'].update(signal_types)
            else:
                attributes['__signal_types__'] = signal_types

            attributes['__gsignals__'] = {
                name: signal.attrs()
                for name, signal in signal_types.items()
            }

        return type(GObject.GObject).__new__(cls, class_name, superclasses, attributes)


class BaseDevice(GObject.GObject, metaclass=SignalsMeta):
    class Signals:
        active = Signal("active", bool)
        busy = Signal("busy", bool)
        enabled = Signal("enabled", bool),
        health = Signal("health", object)
        message = Signal("message", str)

    def __init__(self):
        super().__init__()

        self.__signal__types__ = get_signal_properties(self)

    def __str__(self):
        return '<{}|{}>'.format(self.__class__.__name__, id(self))


class Detector(BaseDevice):
    class Signals:
        activity = Signal("activity", int)

gi.require_version('Gtk', '3.0')
if __name__ == '__main__':

    def show_active(obj, value):
        print("active", obj, value)

    def show_activity(obj, value):
        print("activity", obj, value)

    def run():
        dev = Detector()
        dev.connect('active', show_active)
        dev.connect('activity', show_activity)
        count = 0
        while count < 10:
            dev.emit('active', random.choice((True, False)))
            dev.emit('activity', random.randint(0, 100))
            time.sleep(1)
            count += 1
        Gtk.main_quit()

    GLib.idle_add(run)
    Gtk.main()


