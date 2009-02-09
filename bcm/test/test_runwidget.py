import gtk
import sys
from bcm.utils.log import log_to_console
from mxdc.widgets.runmanager import RunManager
from mxdc.CollectManager import CollectManager
log_to_console()

def main():    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("Run Widget Demo")
    run = RunManager()
    c = CollectManager()
    win.add(c)
    win.show_all()
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()