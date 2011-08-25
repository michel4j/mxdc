
import numpy
import Image
from bcm.utils.science import savitzky_golay

THRESHOLD = 20

    
def get_pin_tip(img, bkg=None, orientation=2):
    SCALE = 4
    w,h = img.size
    img = img.resize((w//SCALE,h//SCALE), Image.BICUBIC)
    
    if bkg is not None:
        bkg = bkg.resize((w//SCALE,h//SCALE), Image.BICUBIC)
        a = numpy.asarray(img.convert('L'))
        b = numpy.asarray(bkg.convert('L'))
        ab = numpy.abs((a-b))
        ab -= ab.mean()
    else:
        ab = numpy.asarray(img.convert('L'))
        ab -= ab.mean()
        
    x1 = numpy.amax(ab, 0) - numpy.amin(ab, 0)
    y1 = numpy.amax(ab, 1) - numpy.amin(ab, 1)
    

    x = savitzky_golay(x1, 15, 0)
    y = savitzky_golay(y1, 15, 0)
    
    xp = list(x > THRESHOLD)
    try:
        if orientation == 2:
            xp.reverse()
            x_tip = len(xp) - xp.index(True)
        else:
            x_tip = xp.index(True)
    except ValueError:
        x_tip = 0
    
    y_max = y.max()
    if y.max() < 2 * THRESHOLD:
        y_mid = len(y)//2
    else:
        y_mid = list(y).index(y_max)
    return (x_tip*SCALE, y_mid*SCALE)