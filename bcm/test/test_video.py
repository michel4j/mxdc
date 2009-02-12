import sys, os
import gtk
sys.path.append('/media/seagate/beamline-control-module')
from bcm.device.video import SimCamera
from mxdc.widgets.video import VideoWidget
from bcm.utils.log import log_to_console

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Video Test")
    
    cam = SimCamera()
    vid = VideoWidget(cam)
    win.add(vid)
    win.show_all()
    
    gtk.main()


if __name__ == '__main__':
    main()  