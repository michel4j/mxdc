

from bcm.utils.science import savitzky_golay, find_peaks
import Image
import ImageChops
import ImageFilter
import numpy
import bisect

THRESHOLD = 20
BORDER = 10


def image_deviation(img1, img2):
    img = ImageChops.difference(img1, img2).filter(ImageFilter.BLUR)
    ab = numpy.asarray(img.convert('L'))
    return ab.std()

def _centroid(a):
    if a.sum() == 0.0:
        return -1
    else:
        return int((numpy.array(range(len(a))) * a).sum()/a.sum())

def _get_object(a):
    p = list(a > THRESHOLD)
    
    if True in p:
        mid = _centroid(a)
        pl = p.index(True)
        pr = len(p) - p[::-1].index(True)  - 1
        span = abs(pr-pl)
        mid = (pr+pl)*0.5
    else:
        mid, span = -1, 1
    return mid, max(span, 1)
    
def get_loop_center(orig, bkg, orientation=2):
    img = ImageChops.difference(orig, bkg).filter(ImageFilter.BLUR)
    ab = numpy.asarray(img.convert('L'))
    x = numpy.max(ab, 0)
    y = numpy.max(ab, 1)[::-1]
    quality = 0
    xp = list(x > THRESHOLD)
    if orientation == 1:
        if True in xp:
            xtip = xp.index(True)
        else:
            xtip = len(xp) - 1
            quality -= 1
    else:
        if True in xp:
            xtip = len(xp) - xp[::-1].index(True)  - 1
        else:
            xtip = 0
            quality -= 1
    ymid = _centroid(y)
    
    spans = numpy.zeros(x.shape)
    mids = numpy.zeros(x.shape)
    for i in range(xtip):
        yl = ab[:,i][::-1]
        mid, span = _get_object(yl)
        spans[i] = span
        mids[i] = mid
    peaks = find_peaks(range(len(spans)), 255-spans, sensitivity=0.05)
    if len(peaks) > 1:
        ls = peaks[-2][0]
        le = peaks[-1][0]
        loop = spans[ls:le]
        lx = 1+numpy.array(range(len(loop)))
        xmid = le - int(numpy.exp(numpy.log(lx).mean()))
        width = loop.mean()
        if xmid > 0:
            ymid = mids[xmid]

    else:
        xmid = xtip
        width = -1
    
    return xmid, len(y)-ymid, width
    

def _normalize(data):
    data = data - data.min()
    return (100.0 * data)/data.max()

def get_pin_cv(img, bkg=None, orientation=2):
    import cv
    cv_img = cv.CreateImageHeader(img.size, cv.IPL_DEPTH_8U, 3)
    cv.SetData(cv_img, img.tostring())
    
    img_gray = cv.CreateImage(cv.GetSize(cv_img), 8, 1)
    img_flt = cv.CreateImage(cv.GetSize(cv_img), 8, 1)
    img_16s = cv.CreateImage(cv.GetSize(cv_img), cv.IPL_DEPTH_16S, 1)
    img_smth = cv.CreateImage(cv.GetSize(cv_img), cv_img.depth, cv_img.nChannels)
    
    cv.Smooth(cv_img, img_smth, cv.CV_MEDIAN)
    cv.CvtColor(cv_img, img_gray, cv.CV_BGR2GRAY)
    
    #cv.Canny(img_gray, img_flt, THRESHOLD, THRESHOLD, 3)
    #numpy.asarray(img_flt[:,:])
    
    cv.Sobel(img_gray, img_16s, 1, 1, 7) 
    cv.Smooth(img_16s, img_16s, cv.CV_BLUR, THRESHOLD//4, THRESHOLD//4)
    ab = numpy.asarray(img_16s[:,:])
    

    ab[:,0:BORDER] = ab[:,BORDER:BORDER+BORDER]
    ab[:,-BORDER:] = ab[:,-2*BORDER:-BORDER]
    ab[0:BORDER,:] = ab[BORDER:BORDER+BORDER,:]
    ab[-BORDER:,:] = ab[-2*BORDER:-BORDER,:]


    # Standard deviations
    x = numpy.std(ab, 0)
    y = numpy.std(ab, 1)
    
    # Cumulative sum from both directions
    #x = numpy.mean(ab, 0).cumsum() + numpy.mean(ab, 0)[::-1].cumsum()[::-1]
    #y = (numpy.mean(ab, 1).cumsum() + numpy.mean(ab, 1)[::-1].cumsum()[::-1])   

    SMOOTH = THRESHOLD + (THRESHOLD+1) % 2
    x = _normalize(savitzky_golay(x, SMOOTH, 0))
    y = _normalize(savitzky_golay(y, SMOOTH, 0))
    
    xp = list(x > 25)
    try:
        if orientation == 2:
            xp.reverse()
            x_tip = len(xp) - xp.index(True)
        else:
            x_tip = xp.index(True)
    except:
        x_tip = len(x)
    
    yp = list(y > 25)
    y_max = y.max()
    
    try:
        yl = yp.index(True)
        yp.reverse()
        yr = len(yp) - yp.index(True)
        y_mid = (yl + yr)//2
    except:
        y_mid = len(y)//2
    
    return (x_tip, y_mid)
