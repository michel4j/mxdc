#!/usr/bin/env python
import sys
import gtk
import gst.play
import gst.interfaces

class VideoWidget(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.connect('destroy', self.on_destroy)
        self.connect('expose-event', self.on_expose)
        self.connect('realize', self.on_realize)
        self.set_size_request(400, 400)
        self.player = gst.play.Play()
        self.player.connect('eos', lambda p: gst.main_quit())

        self.imagesink = gst.element_factory_make('xvimagesink')
        
        # Setup source and sinks
        self.player.set_data_src(gst.element_factory_make('videotestsrc'))
        audio_sink = gst.element_factory_make('alsasink')
        audio_sink.set_property('device', 'hw:0')
        self.player.set_audio_sink(audio_sink)
        self.player.set_video_sink(self.imagesink)
        self.show_all()

    def on_destroy(self, da):
        self.stop()
        self.imagesink.set_xwindow_id(0L)

    def on_expose(self, window, event):
        self.imagesink.set_xwindow_id(self.window.xid)
        
    def stop(self):
        self.player.set_state(gst.STATE_NULL)

    def on_realize(self, da):
        self.imagesink.set_xwindow_id(self.window.xid)
        self.player.set_state(gst.STATE_PLAYING)


    def is_playing(self):
        return self.player.get_state() == gst.STATE_PLAYING
    
    def set_source(self, source):
        self.player.set_location(source)
