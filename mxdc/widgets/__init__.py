import os
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gio, GLib

from mxdc import SHARE_DIR
from mxdc.utils.misc import load_binary_data

resource_data = GLib.Bytes.new(load_binary_data(os.path.join(SHARE_DIR, 'mxdc.gresource')))
resources = Gio.Resource.new_from_data(resource_data)
Gio.resources_register(resources)