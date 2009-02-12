import sys, os
import gtk
sys.path.append('/home/michel/Code/eclipse-ws/beamline-control-module')
from bcm.device.video import AxisCamera, CACamera
from bcm.device.motor import CLSMotor
from mxdc.widgets.video import VideoWidget
from bcm.utils.log import log_to_console

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    #win.set_size_request(320,240)
    win.set_title("Video Test")
    
    #cam = AxisCamera('10.52.4.102')
    cam = CACamera('CAM1608-001:data', CLSMotor('SMTR16083I1021:mm'))
    vid = VideoWidget(cam)
    win.add(vid)
    win.show_all()
    
    try:

        gtk.main()
    finally:
        cam.stop()


if __name__ == '__main__':
    main()  