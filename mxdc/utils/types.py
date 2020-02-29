from gi.repository import GObject

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
    def __init__(self, name, types=(), first=False, last=False):
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
            g_signals = {
                signal.name: signal.attrs()
                for name, signal in signal_types.items()
            }

            if '__gsignals__' in attributes:
                attributes['__gsignals__'].update(g_signals)
            else:
                attributes['__gsignals__'] = g_signals

        return type(GObject.GObject).__new__(cls, class_name, superclasses, attributes)


class SignalObject(GObject.GObject, metaclass=SignalsMeta):
    """
    Base Class for all objects that emit signals
    """
    def __init__(self):
        super().__init__()
