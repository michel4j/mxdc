#!/usr/bin/env python
# -*- coding: UTF8 -*-

import sys
import re, os, time, gc, stat
import gtk, gobject, pango
import Image, ImageEnhance, ImageOps, ImageDraw, ImageFont
import numpy, re, struct
from scipy.misc import toimage, fromimage
import pickle
from Dialogs import select_image

class ImgViewer(gtk.VBox):
    __gsignals__ = {
        'log': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,))
    }
    def __init__(self, size=600):
        self.__gobject_init__() 
        gtk.VBox.__init__(self,False)
        self.disp_size = size
        self.interpolation = Image.ANTIALIAS
        # Put image canvas into a frame
        self.img_frame = gtk.Viewport()
        self.img_frame.set_shadow_type(gtk.SHADOW_IN)
        self.image_canvas = gtk.Image()
        self.image_canvas.connect('realize', self.on_realize)
        self.image_canvas.connect('configure-event', self.on_configure)

        self.img_frame.set_events(gtk.gdk.POINTER_MOTION_MASK
                                   | gtk.gdk.STRUCTURE_MASK)
        self.image_canvas.set_size_request(self.disp_size, self.disp_size)
        self.img_frame.add(self.image_canvas)
        imgbox = gtk.Alignment(xalign=0.5, yalign=0.5)
        imgbox.add(self.img_frame)
        self.pack_start(imgbox, expand=True, fill=False)
        
        # Create toolbar
        self.toolbar = gtk.Toolbar()
        self.toolbar.set_style(gtk.TOOLBAR_ICONS)
        self.open_btn = gtk.ToolButton('gtk-open')
        self.toolbar.insert(self.open_btn, 0)
        self.toolbar.insert(gtk.SeparatorToolItem(),1)
        self.zoom_in_btn = gtk.ToolButton('gtk-zoom-in')
        self.toolbar.insert(self.zoom_in_btn, 2)
        self.zoom_out_btn = gtk.ToolButton('gtk-zoom-out')
        self.toolbar.insert(self.zoom_out_btn, 3)
        self.zoom_fit_btn = gtk.ToolButton('gtk-zoom-fit')
        self.toolbar.insert(self.zoom_fit_btn, 4)
        self.zoom_100_btn = gtk.ToolButton('gtk-zoom-100')
        self.toolbar.insert(self.zoom_100_btn, 5)
        self.toolbar.insert(gtk.SeparatorToolItem(),6)
        icon = gtk.Image()
        icon.set_from_pixbuf ( gtk.gdk.pixbuf_new_from_inline(-1, ''.join(incr_contrast_img), False) )
        self.incr_contrast_btn = gtk.ToolButton(icon)
        self.toolbar.insert(self.incr_contrast_btn, 7)
        icon = gtk.Image()
        icon.set_from_pixbuf ( gtk.gdk.pixbuf_new_from_inline(-1, ''.join(decr_contrast_img), False) )
        self.decr_contrast_btn = gtk.ToolButton(icon)
        self.toolbar.insert(self.decr_contrast_btn, 8)
        self.undo_btn = gtk.ToolButton('gtk-undo')
        self.toolbar.insert(self.undo_btn, 9)
        self.toolbar.insert(gtk.SeparatorToolItem(),10)
        self.prev_btn = gtk.ToolButton('gtk-go-back')
        self.toolbar.insert(self.prev_btn, 11)
        self.next_btn = gtk.ToolButton('gtk-go-forward')
        self.toolbar.insert(self.next_btn, 12)
        self.follow_toggle = gtk.ToggleToolButton('gtk-jump-to')
        self.toolbar.insert(self.follow_toggle, 13)       
        self.toolbar.insert(gtk.SeparatorToolItem(),14)
        
        #image information display
        info_table = gtk.HBox(0,False)
        self.image_label = gtk.Label()
        self.image_info = gtk.Label()
        #self.image_info.set_alignment(1,0.5)
        #self.image_label.set_alignment(0,0.5)
        info_table.pack_start(self.image_label, expand=False, fill=False)
        info_table.pack_end(self.image_info, expand=False, fill=False)
        

        self.pointer = gtk.Label("")
        self.pointer.set_use_markup(True)
        labelitem2 = gtk.ToolItem()
        labelitem2.add(self.pointer)
        self.toolbar.insert(labelitem2, 15)
        
        self.pack_start(info_table, expand=False, fill=True)
        self.pack_start(self.toolbar, expand=False, fill=True)
        self.show_all()
        
        self.contrast_level = 0.0
        self.brightness_factor = 1.0
        self.histogram_shift = 0
        self.image_size = self.disp_size
        self.x_center = self.y_center = self.image_size / 2
        self.follow_frames = False
        self.collecting_data = False
        self.follow_id = None

        # connect signals
        self.open_btn.connect('clicked',self.on_file_open)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)      
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)      
        self.zoom_fit_btn.connect('clicked', self.on_zoom_fit)      
        self.zoom_100_btn.connect('clicked', self.on_zoom_100)
        self.incr_contrast_btn.connect('clicked', self.on_incr_contrast)
        self.decr_contrast_btn.connect('clicked', self.on_decr_contrast)
        #self.incr_brightness_btn.connect('clicked', self.on_incr_brightness)
        #self.decr_brightness_btn.connect('clicked', self.on_decr_brightness)
        self.undo_btn.connect('clicked', self.on_reset_filters)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.follow_toggle.connect('toggled', self.on_follow_toggled)
                                   
        # initially only open_btn is active
        self.zoom_in_btn.set_sensitive(False)
        self.zoom_out_btn.set_sensitive(False)
        self.zoom_fit_btn.set_sensitive(False)
        self.zoom_100_btn.set_sensitive(False)
        self.incr_contrast_btn.set_sensitive(False)
        self.decr_contrast_btn.set_sensitive(False)
        self.undo_btn.set_sensitive(False)
        self.next_btn.set_sensitive(False)
        self.prev_btn.set_sensitive(False)
        self.follow_toggle.set_sensitive(False)
            
        self.toolbar.set_tooltips(True)
        self.is_first_image = True
        self.last_displayed = 0
        self.cursor = None
        self.image_queue = []
        #self.load_pck_image('FRAME.pck')
        #self.display()

    def __set_busy(self, busy ):
        if busy:
            self.cursor = gtk.gdk.Cursor(gtk.gdk.WATCH)
            self.image_canvas.window.set_cursor( self.cursor )
        else:
            self.cursor = None
            self.image_canvas.window.set_cursor( self.cursor )

    def log(self, msg):
        self.emit('log', 'ImageViewer: %s' % msg)
       
    def read_header(self):
        # Read MarCCD header
        header_format = 'I16s39I80x' # 256 bytes
        statistics_format = '3Q7I9I40x128H' #128 + 256 bytes
        goniostat_format = '28i16x' #128 bytes
        detector_format = '5i9i9i9i' #128 bytes
        source_format = '10i16x10i32x' #128 bytes
        file_format = '128s128s64s32s32s32s512s96x' # 1024 bytes
        dataset_format = '512s' # 512 bytes
        image_format = '9437184H'
        marccd_header_format = header_format + statistics_format 
        marccd_header_format +=  goniostat_format + detector_format + source_format 
        marccd_header_format +=  file_format + dataset_format + '512x'
        myfile = open(self.filename,'rb')
        self.tiff_header = myfile.read(1024)
        self.header_pars = struct.unpack(header_format,myfile.read(256))
        self.statistics_pars = struct.unpack(statistics_format,myfile.read(128+256))
        self.goniostat_pars  = struct.unpack(goniostat_format,myfile.read(128))
        self.detector_pars = struct.unpack(detector_format, myfile.read(128))
        self.source_pars = struct.unpack(source_format, myfile.read(128))
        self.file_pars = struct.unpack(file_format, myfile.read(1024))
        self.dataset_pars = struct.unpack(dataset_format, myfile.read(512))
        myfile.close()


        # extract some values from the header
        self.beam_x, self.beam_y = self.goniostat_pars[1]/1e3, self.goniostat_pars[2]/1e3
        self.distance = self.goniostat_pars[0] / 1e3
        self.wavelength = self.source_pars[3] / 1e5
        self.pixel_size = self.detector_pars[1] / 1e6
        self.delta = self.goniostat_pars[24] / 1e3
        self.phi_start =  self.goniostat_pars[(7 + self.goniostat_pars[23])] / 1e3
        self.delta_time = self.goniostat_pars[4] / 1e3
        self.max_intensity = self.statistics_pars[4]
        self.average_intensity = self.statistics_pars[5] / 1e3
        self.overloads = self.header_pars[31]
    
    def set_filename(self, filename):
        self.filename = filename
        # determine file template and frame_number
        file_pattern = re.compile('^(.*)([_.])(\d+)(\..+)?$')
        fm = file_pattern.search(self.filename)
        parts = fm.groups()
        if len(parts) == 4:
            prefix = parts[0] + parts[1]
            if parts[3]:
                file_extension = parts[3]
            else:
                file_extension = ""
            self.file_template = "%s%s0%dd%s" % (prefix, '%', len(parts[2]), file_extension)
            self.frame_number = int (parts[2])
        else:
            self.file_template = None
            self.frame_number = None
        
    def load_image(self):
        self.log("Loading image %s" % (self.filename))

        self.read_header()
                
        # correct gamma
        self.raw_img = Image.open(self.filename)
       
        self.gamma_factor = 80.0 / self.average_intensity
        self.img = self.raw_img.point(lambda x: x * self.gamma_factor).convert('L')
        self.orig_size = max(self.raw_img.size)

        # invert the image to get black spots on white background and resize
        self.img = self.img.point(lambda x: x * -1 + 255)
        self.work_img = self.img.resize( (self.image_size, self.image_size), self.interpolation)
        self.image_info_text = u'exposure=%0.1f ; delta=%0.2f, dist=%0.1f ; angle=%0.2f, wavelength=%0.4f ; <I>=%0.1f, I-max=%0.0f ; #Sat=%0.0f' % (
            self.delta_time, 
            self.delta, self.distance,
            self.phi_start, 
            self.wavelength,
            self.average_intensity,self.max_intensity, self.overloads)
        self.image_label.set_markup(os.path.split(self.filename)[1])
        #self.image_info.set_markup(self.image_info_text)

        

    def delayed_init(self):
        # activate toolbar 
        self.zoom_in_btn.set_sensitive(True)
        self.zoom_out_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.zoom_100_btn.set_sensitive(True)
        self.incr_contrast_btn.set_sensitive(True)
        self.decr_contrast_btn.set_sensitive(True)
        self.undo_btn.set_sensitive(True)
        self.next_btn.set_sensitive(True)
        self.prev_btn.set_sensitive(True)
        self.follow_toggle.set_sensitive(True)
        
        # connect rest of events when first image is loaded
        self.img_frame.connect('motion_notify_event', self.on_mouse_move)
        self.img_frame.connect('button_press_event', self.on_shift_image)
    
    
    def img_bounds(self):
        half_size = self.disp_size / 2
        if self.x_center < half_size: self.x_center = half_size
        if self.y_center < half_size: self.y_center = half_size
        if self.disp_size > self.image_size:
            self.image_size = self.disp_size
            self.x_center, self.y_center = half_size, half_size
        if self.x_center + half_size > self.image_size:
            self.x_center = self.image_size - half_size
        if self.y_center + half_size > self.image_size:
            self.y_center = self.image_size - half_size
        return (self.x_center-half_size, self.y_center-half_size, 
                self.x_center + half_size, self.y_center + half_size)

    def display(self):
        mybounds = self.img_bounds()
        half_size = self.disp_size/2
        scale = self.image_size / float(self.orig_size)
        x = scale * self.beam_x
        y = scale * self.beam_y
        tmp_image = self.work_img.crop(mybounds)
        tmp_image = self.apply_filters(tmp_image)   
        tmp_image = tmp_image.convert('RGBA')
        self.draw_cross(tmp_image)
        self.draw_info(tmp_image)
        imagestr = tmp_image.tostring()
        self.last_displayed = time.time()

        IS_RGBA = tmp_image.mode=='RGBA'
        pixbuf = gtk.gdk.pixbuf_new_from_data(imagestr,gtk.gdk.COLORSPACE_RGB, IS_RGBA, 8, tmp_image.size[0],
                tmp_image.size[1],(IS_RGBA and 4 or 3) * tmp_image.size[0])
        self.image_canvas.set_from_pixbuf(pixbuf)
  
        # keep track of time to prevent loading next frame too quickly 
        # when following images
        self.last_open_time = time.time()
        # enable toolbar and connect mouse events if this is the first image
        if self.is_first_image:
            self.delayed_init()
            self.is_first_image = False

    def apply_filters(self, image):       
        if self.histogram_shift != 0:
            new_img = self.adjust_level(image, self.histogram_shift)
        
        else:
            #using auto_contrast        
            new_img = ImageOps.autocontrast(image,cutoff=self.contrast_level)
        return new_img
                        
    def poll_for_file(self):
        if len(self.image_queue) == 0:
            if self.collecting_data == True:
                return True
            else:
                self.follow_toggle.set_active(False)
                return False
        else:
            next_filename = self.image_queue[0]
        
        if os.path.isfile(next_filename) and (os.stat(next_filename)[stat.ST_SIZE] == 18878464):
            self.set_filename( next_filename )
            self.image_queue.pop(0) # delete loaded image from queue item
            self.load_image()
            self.display()
            return True
        else:
            return True     

    def auto_follow(self):
        # prevent chainloading by only loading images 4 seconds appart
        if time.time() - self.last_displayed < 4:
            return True
        if not (self.frame_number and self.file_template):
            return False
        frame_number = self.frame_number + 1
        filename = self.file_template % (frame_number)
        self.image_queue = []
        self.image_queue.append(filename)
        self.poll_for_file()
        return True        
    
    def set_collect_mode(self, state=True):
        self.collecting_data = state
        if self.collecting_data:
            self.follow_toggle.set_active(state)
            self.follow_frames = True
            self.image_queue = []
            if self.follow_id is not None:
                gobject.source_remove(self.follow_id)
            self.__set_busy(True)
            gobject.timeout_add(500, self.poll_for_file)

    def show_detector_image(self, filename):
        if self.collecting_data and self.follow_frames:
            self.image_queue.append(filename)
            self.log("%d images in queue" % len(self.image_queue) )
        return True     
        
    def zooming_lens(self,Ox,Oy,src_size = 30, zoom_level = 4):
        half_src = src_size / 2
        lens_size = src_size * zoom_level
        half_image = self.orig_size / 2
        src_x = Ox - half_src
        src_y = Oy - half_src
        if src_x < 0: src_x = 0
        if src_y < 0: src_y = 0
        if src_x + src_size > self.orig_size:
            src_x = self.orig_size - src_size
        if src_y + src_size > self.orig_size:
            src_y = self.orig_size - src_size
        tmp_image = self.img.crop((src_x,src_y,src_x+src_size,src_y+src_size)).convert('RGBA')
        tmp_image = tmp_image.resize((lens_size,lens_size),Image.NEAREST)
        tmp_image = ImageOps.expand(tmp_image, border=1, fill=(255, 255, 255))
        tmp_image = ImageOps.expand(tmp_image, border=1, fill=(0, 0, 0))
        imagestr = tmp_image.tostring()

        IS_RGBA = tmp_image.mode=='RGBA'
        pixbuf = gtk.gdk.pixbuf_new_from_data(imagestr,gtk.gdk.COLORSPACE_RGB, IS_RGBA, 8, tmp_image.size[0],
                tmp_image.size[1],(IS_RGBA and 4 or 3) * tmp_image.size[0])
        cursor = gtk.gdk.Cursor(gtk.gdk.display_get_default(), pixbuf, lens_size/2+2, lens_size/2+2)
        self.image_canvas.window.set_cursor(cursor)

    def draw_cross(self, img):
        draw = ImageDraw.Draw(img)
        half_size = self.disp_size / 2
        scale = self.image_size / float(self.orig_size)
        x = self.beam_x*scale + half_size - self.x_center
        y = self.beam_y*scale + half_size - self.y_center
        draw.line((x-5, y, x+5, y),width=1,fill='#0033CC')
        draw.line((x, y-5, x, y+5),width=1,fill='#0033CC')
        return

    def draw_info(self, img):
        draw = ImageDraw.Draw(img)
        #font = ImageFont.load_default()
        font = ImageFont.truetype(os.environ['BCM_PATH']+'/mxdc/gui/images/vera.ttf', 10)
        lines = self.image_info_text.split(', ')
        x = 5
        y = self.disp_size - 50
        for i in range(len(lines)):
            line = lines[i]
            draw.text( (x,y+i*12), line, font=font, fill='#0033CC')
        return

    def resolution(self,x,y):
        displacement = self.pixel_size * numpy.sqrt ( (x -self.beam_x)**2 + (y -self.beam_y)**2 )
        angle = 0.5 * numpy.arctan(displacement/self.distance)
        if angle < 1e-3:
            angle = 1e-3
        return self.wavelength / (2.0 * numpy.sin(angle) )

    def zoom(self, size):
        old_size = self.image_size
        self.image_size = size
        if self.image_size < self.disp_size:
            self.image_size = self.disp_size
        if self.image_size > self.orig_size:
            interpolation = Image.NEAREST
        else:
            interpolation = self.interpolation
        self.work_img = self.img.resize((self.image_size,self.image_size),interpolation)
        scale = float(self.image_size) / old_size
        self.x_center = int(scale * self.x_center) 
        self.y_center = int(scale * self.y_center)

    def adjust_level(self, img, shift):     
        return img.point(lambda x: x * 1 + shift)
    
    # callbacks
    def on_configure(self, obj, event):
        width, height = obj.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(self.image_canvas.window, width, height)
        self.width, self.height = width, height
        return True

    def on_realize(self, obj):
        self.gc = self.image_canvas.window.new_gc()
        self.pl_gc = self.image_canvas.window.new_gc()
        self.pl_gc.foreground = self.image_canvas.get_colormap().alloc_color("green")
        self.ol_gc = self.image_canvas.window.new_gc()
        self.ol_gc.foreground = self.image_canvas.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(2,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.banner_pl = self.image_canvas.create_pango_layout("")
        self.banner_pl.set_font_description(pango.FontDescription("Monospace 7"))
        return True

    def on_incr_brightness(self,widget):
        self.brightness_factor += 0.1
        self.display()
        return True    
    
    def on_decr_brightness(self,widget):
        self.brightness_factor -= 0.1
        self.display()
        return True    
    
    def on_incr_contrast(self,widget):
        if self.contrast_level < 45.0 and self.histogram_shift ==0:
            self.contrast_level += 2.0
        else:
            self.histogram_shift -= 5
            self.contrast_level = 45.0

        self.display()
        return True    

    def on_decr_contrast(self,widget):
        if self.contrast_level >= 2.0 and self.histogram_shift ==0:
            self.contrast_level -= 2.0
        else:
            self.histogram_shift += 5
            self.contrast_level = 0.0
        self.display()
        return True    
    
    def on_reset_filters(self,widget):
        self.contrast_level = 0.0
        self.brightness_factor = 1.0
        self.histogram_shift = 0
        self.image_size = self.disp_size
        self.work_img = self.img.resize((self.image_size,self.image_size),self.interpolation)
        self.display()
        return True    
    
    def on_zoom_in(self,widget):
        size =    self.image_size + 512
        self.zoom(size)
        self.display()
        return True


    def on_zoom_out(self,widget):
        size =    self.image_size - 512
        self.zoom(size)
        self.display()
        return True 
    
    def on_zoom_100(self,widget):
        old_size = self.image_size
        self.image_size = self.orig_size
        self.work_img = self.img.copy()       
        scale = float(self.image_size) / old_size
        self.x_center = int(scale * self.x_center) 
        self.y_center = int(scale * self.y_center) 
        self.display()
        return True 
     
    def on_zoom_fit(self,widget):
        self.image_size = self.disp_size
        self.work_img = self.img.resize((self.image_size,self.image_size),self.interpolation)        
        self.display()
        return True 
        
    def on_shift_image(self,widget,event):
        if event.button != 1:
            return True
        half_size = self.disp_size / 2
        self.x_center = int(event.x - half_size + self.x_center)
        self.y_center = int(event.y - half_size + self.y_center)
        self.display()
        return True
    
    def on_mouse_move(self,widget,event):
        half_size = self.disp_size / 2
        scale = float(self.image_size)/self.orig_size
        Ix = event.x - half_size + self.x_center
        Iy = event.y - half_size + self.y_center
        Ox = int(Ix/scale)
        Oy = int(Iy/scale)
        self.pointer.set_text("<tt>(%04d.%04d) %0.2f Å</tt>"% (Ox, Oy, self.resolution(Ox,Oy)))
        self.pointer.set_use_markup(True)
        if 'GDK_BUTTON2_MASK' in event.state.value_names:
            self.zooming_lens(Ox, Oy)
        else:
            self.image_canvas.window.set_cursor(self.cursor)
        return True

    def on_next_frame(self,widget):
        if not (self.frame_number and self.file_template):
            return True
        frame_number = self.frame_number + 1
        filename = self.file_template % (frame_number)
        if os.path.isfile(filename):
            self.set_filename(filename)
            self.load_image()
            self.display()
        else:
            self.log("File not found: %s" % (filename))
        return True        

    def on_prev_frame(self,widget):
        if not (self.frame_number and self.file_template):
            return True
        frame_number = self.frame_number - 1
        filename = self.file_template % (frame_number)
        if os.path.isfile(filename):
            self.frame_number = frame_number
            self.set_filename(filename)
            self.load_image()
            self.display()
        else:
            self.log("File not found: %s" % (filename))
        return True

    def on_file_open(self,widget):
        filename = select_image()
        if filename and os.path.isfile(filename):
            self.set_filename(filename)
            self.load_image()
            self.display()
        return True

    def on_follow_toggled(self,widget):
        if widget.get_active():
            self.follow_frames = True
            if not self.collecting_data:
                self.follow_id = gobject.timeout_add(500, self.auto_follow)
        else:
            self.__set_busy(False)
            if self.follow_id is not None:
                gobject.source_remove(self.follow_id)
                self.follow_id = None
            self.follow_frames = False
        return True
    
gobject.type_register(ImgViewer)

        
        
# icons for contrast buttons        
incr_contrast_img =   [ ""
  "GdkP"
  "\0\0\5Y"
  "\2\1\0\2"
  "\0\0\0X"
  "\0\0\0\26"
  "\0\0\0\26"
  "\264\0\0\0\0\1\0\0\0\1\202\0\0\0\2\202\0\0\0\3\202\0\0\0\2\1\0\0\0\1"
  "\214\0\0\0\0\14\0\0\0\1\0\0\0;\0\0\0\233\0\0\0\334\0\0\0\372\0\0\0\373"
  "\0\0\0\335\0\0\0\240\0\0\0E\0\0\0\12\0\0\0\4\0\0\0\1\211\0\0\0\0\5\0"
  "\0\0\1\0\0\0\231GGG\377\343\343\343\377\372\372\372\377\202\375\375\375"
  "\377\7\371\371\371\377\323\323\323\377CCC\377\0\0\0\246\0\0\0\23\0\0"
  "\0\7\0\0\0\1\207\0\0\0\0\6\0\0\0\1\0\0\0\272\267\267\267\377\374\374"
  "\374\377\372\372\372\377\367\367\367\377\204\366\366\366\377\6\327\327"
  "\327\377\225\225\225\377\0\0\0\306\0\0\0\32\0\0\0\10\0\0\0\1\205\0\0"
  "\0\0\11\0\0\0\1\0\0\0\232\260\260\260\377\372\372\372\377\365\365\365"
  "\377\241\241\241\377MMM\377\36\36\36\377\362\362\362\377\202\363\363"
  "\363\377\7\364\364\364\377\321\321\321\377\220\220\220\377\0\0\0\255"
  "\0\0\0\32\0\0\0\7\0\0\0\1\204\0\0\0\0\10\0\0\0;AAA\377\370\370\370\377"
  "\361\361\361\377mmm\377&&&\377```\377222\377\202\363\363\363\377\203"
  "\364\364\364\377\5\320\320\320\377333\377\0\0\0`\0\0\0\23\0\0\0\4\203"
  "\0\0\0\0\13\0\0\0\1\0\0\0\233\327\327\327\377\367\367\367\377\237\237"
  "\237\377555\377```\377222\377\1\1\1\377\363\363\363\377\364\364\364\377"
  "\202\365\365\365\377\7\366\366\366\377\354\354\354\377\243\243\243\377"
  "\0\0\0\265\0\0\0%\0\0\0\12\0\0\0\1\202\0\0\0\0\7\0\0\0\2\0\0\0\334\364"
  "\364\364\377\362\362\362\377XXX\377```\377222\377\202\0\0\0\377\1\364"
  "\364\364\377\202\365\365\365\377\202\366\366\366\377\6\367\367\367\377"
  "\302\302\302\377\0\0\0\346\0\0\0""4\0\0\0\21\0\0\0\2\202\0\0\0\0\6\0"
  "\0\0\3\0\0\0\372\371\371\371\377\361\361\361\377HHH\377EEE\377\203\0"
  "\0\0\377\202\365\365\365\377\202\366\366\366\377\202\367\367\367\377"
  "\5\321\321\321\377\0\0\0\374\0\0\0@\0\0\0\27\0\0\0\3\202\0\0\0\0\6\0"
  "\0\0\3\0\0\0\373\364\364\364\377\362\362\362\377LLL\377+++\377\203\0"
  "\0\0\377\1\365\365\365\377\202\366\366\366\377\202\367\367\367\377\6"
  "\370\370\370\377\323\323\323\377\0\0\0\374\0\0\0F\0\0\0\32\0\0\0\4\202"
  "\0\0\0\0\7\0\0\0\3\0\0\0\335\367\367\367\377\362\362\362\377[[[\3773"
  "33\377\1\1\1\377\202\0\0\0\377\202\366\366\366\377\202\367\367\367\377"
  "\7\370\370\370\377\371\371\371\377\310\310\310\377\0\0\0\347\0\0\0F\0"
  "\0\0\32\0\0\0\4\202\0\0\0\0\7\0\0\0\3\0\0\0\240\342\342\342\377\364\364"
  "\364\377\240\240\240\377&&&\377\30\30\30\377\202\0\0\0\377\2\366\366"
  "\366\377\367\367\367\377\202\370\370\370\377\7\371\371\371\377\361\361"
  "\361\377\244\244\244\377\0\0\0\275\0\0\0@\0\0\0\27\0\0\0\3\202\0\0\0"
  "\0\7\0\0\0\2\0\0\0EGGG\377\373\373\373\377\365\365\365\377ooo\377\12"
  "\12\12\377\202\0\0\0\377\1\367\367\367\377\202\370\370\370\377\202\371"
  "\371\371\377\6\302\302\302\377333\377\0\0\0[\0\0\0""5\0\0\0\21\0\0\0"
  "\2\202\0\0\0\0\11\0\0\0\1\0\0\0\12\0\0\0\246\262\262\262\377\371\371"
  "\371\377\366\366\366\377\240\240\240\377<<<\377\7\7\7\377\202\370\370"
  "\370\377\202\371\371\371\377\7\322\322\322\377\210\210\210\377\0\0\0"
  "\275\0\0\0I\0\0\0%\0\0\0\12\0\0\0\1\203\0\0\0\0\7\0\0\0\4\0\0\0\23\0"
  "\0\0\306\232\232\232\377\350\350\350\377\370\370\370\377\367\367\367"
  "\377\202\370\370\370\377\11\366\366\366\377\353\353\353\377\315\315\315"
  "\377\210\210\210\377\0\0\0\323\0\0\0Q\0\0\0""3\0\0\0\24\0\0\0\4\204\0"
  "\0\0\0\22\0\0\0\1\0\0\0\7\0\0\0\32\0\0\0\255<<<\377\267\267\267\377\327"
  "\327\327\377\331\331\331\377\326\326\326\377\320\320\320\377\254\254"
  "\254\377333\377\0\0\0\275\0\0\0Q\0\0\0""7\0\0\0\32\0\0\0\7\0\0\0\1\205"
  "\0\0\0\0\6\0\0\0\1\0\0\0\10\0\0\0\32\0\0\0`\0\0\0\265\0\0\0\346\202\0"
  "\0\0\374\10\0\0\0\347\0\0\0\275\0\0\0[\0\0\0I\0\0\0""3\0\0\0\32\0\0\0"
  "\10\0\0\0\1\207\0\0\0\0\6\0\0\0\1\0\0\0\7\0\0\0\23\0\0\0$\0\0\0""4\0"
  "\0\0@\202\0\0\0F\6\0\0\0@\0\0\0""4\0\0\0$\0\0\0\23\0\0\0\7\0\0\0\1\211"
  "\0\0\0\0\5\0\0\0\1\0\0\0\4\0\0\0\12\0\0\0\21\0\0\0\27\202\0\0\0\32\5"
  "\0\0\0\27\0\0\0\21\0\0\0\12\0\0\0\4\0\0\0\1\214\0\0\0\0\2\0\0\0\1\0\0"
  "\0\2\204\0\0\0\3\2\0\0\0\2\0\0\0\1\206\0\0\0\0"]
  
decr_contrast_img = [ ""
  "GdkP"
  "\0\0\5s"
  "\2\1\0\2"
  "\0\0\0X"
  "\0\0\0\26"
  "\0\0\0\26"
  "\264\0\0\0\0\1\0\0\0\1\202\0\0\0\2\202\0\0\0\3\202\0\0\0\2\1\0\0\0\1"
  "\214\0\0\0\0\14\0\0\0\1\0\0\0;\0\0\0\233\0\0\0\334\0\0\0\372\0\0\0\373"
  "\0\0\0\335\0\0\0\240\0\0\0E\0\0\0\12\0\0\0\4\0\0\0\1\211\0\0\0\0\5\0"
  "\0\0\1\0\0\0\231GGG\377\343\343\343\377\372\372\372\377\202\375\375\375"
  "\377\7\371\371\371\377\323\323\323\377CCC\377\0\0\0\246\0\0\0\23\0\0"
  "\0\7\0\0\0\1\207\0\0\0\0\10\0\0\0\1\0\0\0\272\267\267\267\377\367\367"
  "\367\377\361\361\361\377\352\352\352\377\344\344\344\377\365\365\365"
  "\377\202\366\366\366\377\6\327\327\327\377\225\225\225\377\0\0\0\306"
  "\0\0\0\32\0\0\0\10\0\0\0\1\205\0\0\0\0\11\0\0\0\1\0\0\0\232\260\260\260"
  "\377\350\350\350\377\274\274\274\377\222\222\222\377\203\203\203\377"
  "}}}\377\353\353\353\377\202\363\363\363\377\7\364\364\364\377\321\321"
  "\321\377\220\220\220\377\0\0\0\255\0\0\0\32\0\0\0\7\0\0\0\1\204\0\0\0"
  "\0\12\0\0\0;AAA\377\366\366\366\377\272\272\272\377\210\210\210\377~"
  "~~\377\206\206\206\377\177\177\177\377\322\322\322\377\363\363\363\377"
  "\203\364\364\364\377\5\320\320\320\377333\377\0\0\0`\0\0\0\23\0\0\0\4"
  "\203\0\0\0\0\13\0\0\0\1\0\0\0\233\327\327\327\377\344\344\344\377\222"
  "\222\222\377\200\200\200\377\206\206\206\377\177\177\177\377xxx\377\273"
  "\273\273\377\362\362\362\377\202\365\365\365\377\7\366\366\366\377\354"
  "\354\354\377\243\243\243\377\0\0\0\265\0\0\0%\0\0\0\12\0\0\0\1\202\0"
  "\0\0\0\7\0\0\0\2\0\0\0\334\364\364\364\377\322\322\322\377\205\205\205"
  "\377\206\206\206\377\177\177\177\377\202xxx\377\3\271\271\271\377\345"
  "\345\345\377\365\365\365\377\202\366\366\366\377\6\367\367\367\377\302"
  "\302\302\377\0\0\0\346\0\0\0""4\0\0\0\21\0\0\0\2\202\0\0\0\0\4\0\0\0"
  "\3\0\0\0\372\371\371\371\377\307\307\307\377\202\202\202\202\377\203"
  "xxx\377\2\273\273\273\377\331\331\331\377\202\366\366\366\377\202\367"
  "\367\367\377\5\321\321\321\377\0\0\0\374\0\0\0@\0\0\0\27\0\0\0\3\202"
  "\0\0\0\0\6\0\0\0\3\0\0\0\373\364\364\364\377\315\315\315\377\203\203"
  "\203\377\177\177\177\377\203xxx\377\3\273\273\273\377\327\327\327\377"
  "\366\366\366\377\202\367\367\367\377\6\370\370\370\377\323\323\323\377"
  "\0\0\0\374\0\0\0F\0\0\0\32\0\0\0\4\202\0\0\0\0\6\0\0\0\3\0\0\0\335\367"
  "\367\367\377\347\347\347\377\205\205\205\377\200\200\200\377\203xxx\377"
  "\2\274\274\274\377\331\331\331\377\202\367\367\367\377\7\370\370\370"
  "\377\371\371\371\377\310\310\310\377\0\0\0\347\0\0\0F\0\0\0\32\0\0\0"
  "\4\202\0\0\0\0\7\0\0\0\3\0\0\0\240\342\342\342\377\364\364\364\377\223"
  "\223\223\377~~~\377|||\377\202xxx\377\2\274\274\274\377\344\344\344\377"
  "\202\370\370\370\377\7\371\371\371\377\361\361\361\377\244\244\244\377"
  "\0\0\0\275\0\0\0@\0\0\0\27\0\0\0\3\202\0\0\0\0\7\0\0\0\2\0\0\0EGGG\377"
  "\373\373\373\377\336\336\336\377\207\207\207\377zzz\377\202xxx\377\3"
  "\300\300\300\377\364\364\364\377\370\370\370\377\202\371\371\371\377"
  "\6\302\302\302\377333\377\0\0\0[\0\0\0""5\0\0\0\21\0\0\0\2\202\0\0\0"
  "\0\13\0\0\0\1\0\0\0\12\0\0\0\246\262\262\262\377\371\371\371\377\342"
  "\342\342\377\222\222\222\377\201\201\201\377ooo\377\351\351\351\377\370"
  "\370\370\377\202\371\371\371\377\7\322\322\322\377\210\210\210\377\0"
  "\0\0\275\0\0\0I\0\0\0%\0\0\0\12\0\0\0\1\203\0\0\0\0\22\0\0\0\4\0\0\0"
  "\23\0\0\0\306\232\232\232\377\350\350\350\377\364\364\364\377\350\350"
  "\350\377\365\365\365\377\370\370\370\377\366\366\366\377\353\353\353"
  "\377\315\315\315\377\210\210\210\377\0\0\0\323\0\0\0Q\0\0\0""3\0\0\0"
  "\24\0\0\0\4\204\0\0\0\0\22\0\0\0\1\0\0\0\7\0\0\0\32\0\0\0\255<<<\377"
  "\267\267\267\377\327\327\327\377\331\331\331\377\326\326\326\377\320"
  "\320\320\377\254\254\254\377333\377\0\0\0\275\0\0\0Q\0\0\0""7\0\0\0\32"
  "\0\0\0\7\0\0\0\1\205\0\0\0\0\6\0\0\0\1\0\0\0\10\0\0\0\32\0\0\0`\0\0\0"
  "\265\0\0\0\346\202\0\0\0\374\10\0\0\0\347\0\0\0\275\0\0\0[\0\0\0I\0\0"
  "\0""3\0\0\0\32\0\0\0\10\0\0\0\1\207\0\0\0\0\6\0\0\0\1\0\0\0\7\0\0\0\23"
  "\0\0\0$\0\0\0""4\0\0\0@\202\0\0\0F\6\0\0\0@\0\0\0""4\0\0\0$\0\0\0\23"
  "\0\0\0\7\0\0\0\1\211\0\0\0\0\5\0\0\0\1\0\0\0\4\0\0\0\12\0\0\0\21\0\0"
  "\0\27\202\0\0\0\32\5\0\0\0\27\0\0\0\21\0\0\0\12\0\0\0\4\0\0\0\1\214\0"
  "\0\0\0\2\0\0\0\1\0\0\0\2\204\0\0\0\3\2\0\0\0\2\0\0\0\1\206\0\0\0\0"]


      
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_title("Diffraction Image Viewer")
    myview = ImgViewer(size=768)
    hbox = gtk.HBox(False)
    hbox.pack_start(myview)
    win.add(hbox)
    win.show_all()

    if len(sys.argv) == 2:
        myview.set_filename(sys.argv[1])
        myview.load_image()
        myview.display()
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()

if __name__ == '__main__':
    main()
