import threading
import time
import gtk
import gobject

class AppWindow(gtk.Window):
    def __init__(self):
        gtk.Window.__init__(self)
        self.set_size_request(200,200)
        self.btn = gtk.Button('Start Thread')
        self.add(self.btn)
        self.btn.connect('clicked', self.on_start_thread)
        self.connect('destroy', lambda x: gtk.main_quit())
    
    def on_start_thread(self, obj):
        self.worker = threading.Thread(target=self.do_work)
        self.worker.setDaemon(True)
        self.worker.start()
    
    def do_work(self):
        print 'Starting new thread'
        for i in range(1000):
            print 'Processing is %0.2f %% complete' % (i/10.0)
            time.sleep(0.01)
        print 'Thread done'
            


if __name__ == '__main__':
    win = AppWindow()
    win.show_all()
    gobject.threads_init()
    gtk.main()
    