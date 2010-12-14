import Image
import array

try:
    import cairo
    assert cairo.version >= '1.4.0'
    using_cairo = True
    
except:
    import ImageDraw
    using_cairo = False

def add_decorations1(img, x, y, w, h):
    _tick_size = 8
    if img.mode == 'L':
        img = img.convert('RGB')
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size
    
    #draw cross
    draw.line([(x-_tick_size, y), (x+_tick_size, y)], fill='#c39')
    draw.line([(x, y-_tick_size), (x, y+_tick_size)], fill='#c39')
    
    
    if w  >= img_w or h  >= img_h:
        return img
    
    #draw slits
    hw = int(0.5 * w)
    hh = int(0.5 * w)
    draw.line([x-hw, y-hh, x-hw, y-hh+_tick_size], fill='#c39')
    draw.line([x-hw, y-hh, x-hw+_tick_size, y-hh], fill='#c39')
    draw.line([x+hw, y+hh, x+hw, y+hh-_tick_size], fill='#c39')
    draw.line([x+hw, y+hh, x+hw-_tick_size, y+hh], fill='#c39')

    draw.line([x-hw, y+hh, x-hw, y+hh-_tick_size], fill='#c39')
    draw.line([x-hw, y+hh, x-hw+_tick_size, y+hh], fill='#c39')
    draw.line([x+hw, y-hh, x+hw, y-hh+_tick_size], fill='#c39')
    draw.line([x+hw, y-hh, x+hw-_tick_size, y-hh], fill='#c39')

    return img


def add_decorations(img, x, y, bw, bh):
    tick = 8
    img = img.convert('RGBA')
    
    w, h = img.size
    hw = bw/2
    hh = bh/2
    if using_cairo:
        src = array.array('B', img.tostring('raw', 'RGBA', 0, 1))
        surface = cairo.ImageSurface.create_for_data(src, cairo.FORMAT_ARGB32,
                                              w, h, w*4)
        cr = cairo.Context(surface)
        cr.set_source_rgba(1.0, 0.4, 0.2, 1.0)
        cr.set_line_width(max(cr.device_to_user_distance(0.5, 0.5)))
        cr.set_dash([4,2])

        # cross center
        cr.move_to(x-tick, y)
        cr.line_to(x+tick, y)
        cr.stroke()
        cr.move_to(x, y+tick)
        cr.line_to(x, y-tick)
        cr.stroke()
              
        # beam size
        cr.set_dash([4,4])
        cr.arc(x, y, hh-1.0, 0, 2.0 * 3.14)
        cr.stroke()
        
        # create overlay img
        ovl_img = Image.frombuffer("RGBA", (surface.get_width(), surface.get_height()),
                                   surface.get_data(), 'raw', 'RGBA', 0, 1)
        img = ovl_img
        
    else:
        draw = ImageDraw.Draw(img)
        
        #draw cross
        draw.line([(x-tick, y), (x+tick, y)], fill='#c39')
        draw.line([(x, y-tick), (x, y+tick)], fill='#c39')
        
                
        #draw slits
        hw = int(0.5 * bw)
        hh = int(0.5 * bh)
        draw.arc([x-hw, y-hh, x+hw, y+hh], 0, 360, fill='#c39')

    return img
