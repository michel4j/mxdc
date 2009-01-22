from mxdc.gui.RunWidget import RunWidget
import gtk
import sys


def main():    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("Run Widget Demo")
    run = RunWidget()
    
    win.add(run)
    win.show_all()
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()