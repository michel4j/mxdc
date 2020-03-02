import random
import os
import sys
import gi
gi.require_version('Gtk', '3.0')

from twisted.internet import gtk3reactor
import threading

gtk3reactor.install()

from gi.repository import GLib, Gtk, GObject
import time
from twisted.internet import reactor
from base import SignalObject

class BaseDevice(SignalObject):
    active = GObject.Signal("active", arg_types=(bool,))

class Detector(BaseDevice):
    activity = GObject.Signal("activity", arg_types=(int,))



if __name__ == '__main__':

    def show_active(obj, value):
        print("active", obj, value)

    def show_activity(obj, value):
        print("activity", obj, value)

    def run():
        dev = Detector()
        dev.active.connect(show_active)
        dev.activity.connect(show_activity)
        count = 0
        while count < 50:
            dev.transmit('active', True)
            dev.transmit('activity', random.randint(0, 100))
            time.sleep(1)
            count += 1
        reactor.stop()

    worker_thread = threading.Thread(target=run)
    worker_thread.setDaemon(True)
    reactor.callLater(0, worker_thread.start)
    
    reactor.run()


