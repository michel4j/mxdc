import ImageDraw
import Image
import math

def add_decorations(img, x, y, w, h):
    _tick_size = 8
    draw = ImageDraw.Draw(img)
    
    img_w, img_h = img.size
    
    #draw cross
    draw.line([(x-_tick_size-1, y-1), (x+_tick_size-1, y-1)], fill=196)
    draw.line([(x-1, y-_tick_size-1), (x-1, y+_tick_size-1)], fill=196)
    draw.line([(x-_tick_size, y), (x+_tick_size, y)], fill=64)
    draw.line([(x, y-_tick_size), (x, y+_tick_size)], fill=64)
    
    
    if w  >= img_w or h  >= img_h:
        return img
    
    #draw slits
    hw = int(0.5 * w)
    hh = int(0.5 * w)
    draw.line([x-hw, y-hh, x-hw, y-hh+_tick_size], fill=128)
    draw.line([x-hw, y-hh, x-hw+_tick_size, y-hh], fill=128)
    draw.line([x+hw, y+hh, x+hw, y+hh-_tick_size], fill=128)
    draw.line([x+hw, y+hh, x+hw-_tick_size, y+hh], fill=128)

    draw.line([x-hw, y+hh, x-hw, y+hh-_tick_size], fill=128)
    draw.line([x-hw, y+hh, x-hw+_tick_size, y+hh], fill=128)
    draw.line([x+hw, y-hh, x+hw, y-hh+_tick_size], fill=128)
    draw.line([x+hw, y-hh, x+hw-_tick_size, y-hh], fill=128)

    return img
