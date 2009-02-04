import ImageDraw
import Image
import math

def add_decorations(bl, img):
    _tick_size = 8
    draw = ImageDraw.Draw(img)
    cross_x = bl.cross_x.get_position()
    cross_y = bl.cross_y.get_position()
    img_w,img_h = img.size
    scale_factor = 1.0
    pixel_size = 5.34e-3 * math.exp( -0.18 * bl.sample_zoom.get_position())
    
    #draw cross
    draw.line([(cross_x-_tick_size, cross_y), (cross_x+_tick_size, cross_y)], fill=128)
    draw.line([(cross_x, cross_y-_tick_size), (cross_x, cross_y+_tick_size)], fill=128)
    
    #draw slits
    slits_x = bl.beam_x.get_position()
    slits_y = bl.beam_y.get_position()   
    slits_width  = bl.beam_w.get_position() / pixel_size
    slits_height = bl.beam_h.get_position() / pixel_size
    
    #if slits_width  >= img_w or slits_height  >= img_h:
    #    return img
    
    x = int((cross_x - (slits_x / pixel_size)) * scale_factor)
    y = int((cross_y - (slits_y / pixel_size)) * scale_factor)
    hw = int(0.5 * slits_width * scale_factor)
    hh = int(0.5 * slits_height * scale_factor)
    draw.line([x-hw, y-hh, x-hw, y-hh+_tick_size], fill=128)
    draw.line([x-hw, y-hh, x-hw+_tick_size, y-hh], fill=128)
    draw.line([x+hw, y+hh, x+hw, y+hh-_tick_size], fill=128)
    draw.line([x+hw, y+hh, x+hw-_tick_size, y+hh], fill=128)

    draw.line([x-hw, y+hh, x-hw, y+hh-_tick_size], fill=128)
    draw.line([x-hw, y+hh, x-hw+_tick_size, y+hh], fill=128)
    draw.line([x+hw, y-hh, x+hw, y-hh+_tick_size], fill=128)
    draw.line([x+hw, y-hh, x+hw-_tick_size, y-hh], fill=128)

    return img
