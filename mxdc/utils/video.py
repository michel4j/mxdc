from PIL import Image
import array
import cairo
import sys


def add_decorations(img, x, y, bw, bh):
    tick = 8
    img = img.convert('RGBA')
    
    w, h = img.size
    hw = bw/2
    hh = bh/2
    src = array.array('B', img.tobytes('raw', 'RGBA', 0, 1))
    surface = cairo.ImageSurface.create_for_data(src, cairo.FORMAT_ARGB32,
                                          w, h, w*4)
    cr = cairo.Context(surface)
    cr.set_source_rgba(0.2, 0.4, 1.0, 0.7)
    cr.set_line_width(max(cr.device_to_user_distance(1.0, 1.0)))
    cr.set_dash([], 0)

    # cross center
    cr.move_to(x-tick, y)
    cr.line_to(x+tick, y)
    cr.stroke()
    cr.move_to(x, y+tick)
    cr.line_to(x, y-tick)
    cr.stroke()
          
    # beam size
    cr.set_dash([6,6])
    cr.arc(x, y, hh-1.0, 0, 2.0 * 3.14)
    cr.stroke()
    
    # create overlay img
    ovl_img = Image.frombuffer("RGBA", (surface.get_width(), surface.get_height()),
                               surface.get_data(), 'raw', 'RGBA', 0, 1)
    img = ovl_img
    return img

def add_hc_decorations(img, x1, x2, y1, y2):
    img = img.convert('RGBA')
    w, h = img.size
    src = array.array('B', img.tobytes('raw', 'RGBA', 0, 1))
    surface = cairo.ImageSurface.create_for_data(src, cairo.FORMAT_ARGB32, w, h, w*4)
    cr = cairo.Context(surface)
    cr.set_source_rgba(0.1, 1.0, 0.0, 1.0)
    cr.set_line_width(0.5)
    cr.rectangle(x1, y1, x2-x1, y2-y1)
    cr.stroke()
    
    ovl_img = Image.frombuffer("RGBA", (surface.get_width(), surface.get_height()),
                               surface.get_data(), 'raw', 'RGBA', 0, 1)
    img = ovl_img
    return img

def image_to_surface(im):
    """Transform a PIL Image into a Cairo ImageSurface."""

    assert sys.byteorder == 'little', "We don't support big endian"
    if im.mode != 'RGBA':
        im = im.convert('RGBA')

    s = im.tobytes('raw', 'BGRA')
    a = array.array('B', s)
    dest = cairo.ImageSurface(cairo.FORMAT_ARGB32, im.size[0], im.size[1])
    ctx = cairo.Context(dest)
    non_premult_src_wo_alpha = cairo.ImageSurface.create_for_data(
        a, cairo.FORMAT_RGB24, im.size[0], im.size[1])
    non_premult_src_alpha = cairo.ImageSurface.create_for_data(
        a, cairo.FORMAT_ARGB32, im.size[0], im.size[1])
    ctx.set_source_surface(non_premult_src_wo_alpha)
    ctx.mask_surface(non_premult_src_alpha)
    return dest

