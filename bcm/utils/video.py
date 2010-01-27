import ImageDraw

def add_decorations(img, x, y, w, h):
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
