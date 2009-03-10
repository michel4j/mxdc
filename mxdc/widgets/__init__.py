import os
import sys
import gtk

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data/icons')
    
def _register_icons():
    icons = ['fullscreen', 'media-play', 'media-stop', 'media-pause',
             'media-next', 'media-prev', 'contrast', 'brightness', 'internet']

    items = []
    for icon in icons:
        stock = 'gtk-%s'  % icon
        items.append((stock, '', 0, 0, None))             

    gtk.stock_add(items)
    factory = gtk.IconFactory()
    factory.add_default()
    for icon in icons:
        fn = 'stock_%s.png' % icon
        stock = 'gtk-%s'  % icon
        stock_id = 'stock-%s' % icon
        pixbuf = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR, fn))
        icon_set = gtk.IconSet(pixbuf)
        factory.add(stock, icon_set)
        id_name = stock_id.upper().replace('-','_')
        try:
            id = getattr(gtk,id_name)
        except:
            setattr(gtk, id_name, stock)

try:
    id = gtk.STOCK_MEDIA_PLAY
except:
    _register_icons()