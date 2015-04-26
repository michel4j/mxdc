import os
import sys
from gi.repository import Gtk
from gi.repository import GdkPixbuf

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data/icons')
    
def _register_icons():
    icons = ['contrast', 'brightness']

    factory = Gtk.IconFactory()
    factory.add_default()
    for icon in icons:
        fn = 'stock_%s.png' % icon
        stock = 'mxdc-%s'  % icon
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(os.path.join(DATA_DIR, fn))
        icon_set = Gtk.IconSet(pixbuf)
        factory.add(stock, icon_set)

"""
def _register_icon_reuse():
    extra_icons =  ['idle','good','bad','part-cloudy',
                    'sunny','cloudy','rainy','stormy','hcane',
                    'dunknown','dgood','dwarn','dbad','ddisabled'
                    ]
    robot_icons = ['error', 'setup', 'idle', 'standby', 'warning']
    
    # We're too lazy to make our own icons, so we use regular stock icons.
    icons = [
        ('mxdc-replace', Gtk.STOCK_SAVE_AS),
        ('mxdc-resume', Gtk.STOCK_EXECUTE),
        ('mxdc-pause', Gtk.STOCK_MEDIA_PAUSE),
        ('mxdc-stop', Gtk.STOCK_MEDIA_STOP),
        ('mxdc-collect', Gtk.STOCK_MEDIA_PLAY),
        ('mxdc-start', Gtk.STOCK_MEDIA_PLAY),
        ('mxdc-scan', Gtk.STOCK_MEDIA_PLAY),
        ('mxdc-stop-scan', Gtk.STOCK_MEDIA_STOP),
    ]

    items = [
        ('mxdc-replace','_Replace', 0, 0, None),
        ('mxdc-resume', '_Resume', 0, 0, None),
        ('mxdc-collect', '_Collect', 0, 0, None),
        ('mxdc-start', '_Start', 0, 0, None),
        ('mxdc-pause', '_Pause', 0, 0, None),
        ('mxdc-stop', 'S_top', 0, 0, None),
        ('mxdc-scan', '_Start Scan', 0, 0, None),
        ('mxdc-stop-scan', 'S_top Scan', 0, 0, None),
        ('mxdc-pause-scan', '_Pause Scan', 0, 0, None),
        ('mxdc-resume-scan', '_Resume Scan', 0, 0, None),
    ]
    
    Gtk.stock_add(items)
    factory = Gtk.IconFactory()
    factory.add_default()
    for new_stock, alias in icons:
        icon_set = Gtk.icon_factory_lookup_default(alias)
        factory.add(new_stock, icon_set)
    
    for icon in extra_icons:
        fn = 'stock_%s.png' % icon
        stock_id = 'mxdc-%s' % icon
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(os.path.join(DATA_DIR, fn))
        icon_set = Gtk.IconSet(pixbuf)
        factory.add(stock_id, icon_set)
    
    for icon in robot_icons:
        fn = 'robot-%s.png' % icon
        stock_id = 'robot-%s' % icon
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(os.path.join(DATA_DIR, fn))
        icon_set = Gtk.IconSet(pixbuf)
        factory.add(stock_id, icon_set)

"""
_register_icons()    
#_register_icon_reuse()
