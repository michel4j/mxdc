import scipy
from scipy import optimize, array, exp
 
def _res(p, y, x):
    vals = gaussian(x,p)
    err=(y-vals)
    return err

def gaussian(x,p):
    """
    gaus(x, p=[A, x0, s, yoffset]) - with input x vector and parameter list p, this function returns a 
    gaussian vector y
    x - input independent variable
    y - output dependent variable
    A - input amplitude
    x0 - input x value at the peak (mean)
    s - input standard deviation, sigma
    yoffset - input baseline y offset
    """
    return (p[0] * exp( -(x-p[1])**2 / (2.0*p[2]**2) ) + p[3])


def gaussian_fit(x,y):
    """
    gauss_fit(x, y) - with input x, y vectors this function fits the data to a single gaussian and returns
    the fitted parameters [A, x0, s, yoffset]
    x - input independent variable
    y - input dependent variable
    A - output amplitude
    x0 - output x value at the peak (mean)
    s - standard deviation, sigma
    yoffset - baseline y offset

    The FWHM can be calulated as (s * 2.35)
    
    """
    pars = histogram_fit(x,y)
    p0= [pars[2], pars[1],pars[0]/2.35,0.0]
    p1,lsqres=optimize.leastsq(_res, p0, args=(y,x), maxfev=10000)
    return p1, lsqres
    
def histogram_fit(x,y):
    """
    calcfwhm(x,y) - with input x,y vector this function calculates fwhm and returns
    (fwhm,xpeak,ymax, fwhm_x_left, fwhm_x_right)
    x - input independent variable
    y - input dependent variable
    fwhm - return full width half maximum
    xpeak - return x value at y = ymax
    
    """
    
    ymin,ymax = min(y),max(y)
    y_hpeak = ymin + .5 *(ymax-ymin)
    x_hpeak = []
    NPT = len(x)
    i1 = 0
    i2 = NPT
    i = 0
    while (y[i] < y_hpeak) and i< NPT:   
        i+= 1
    i1 = i
    i = NPT-1
    while (y[i] < y_hpeak) and i>0:   
        i-= 1
    i2 = i

    if y[i1] == y_hpeak: 
        x_hpeak_l = x[i1]
    else:
        x_hpeak_l = (y_hpeak-y[i1-1])/(y[i1]-y[i1-1])*(x[i1]-x[i1-1])+x[i1-1]
    if y[i2] == y_hpeak: 
        x_hpeak_r = x[i2]
    else:
        x_hpeak_r = (y_hpeak-y[i2-1])/(y[i2]-y[i2-1])*(x[i2]-x[i2-1])+x[i2-1]
    if i1 == 0: x_hpeak_l = x[0]
    if i2 == 0: x_hpeak_r = x[0]
    x_hpeak = [x_hpeak_l,x_hpeak_r]
    fwhm = abs(x_hpeak[1]-x_hpeak[0])
    for i in range(NPT):
        if y[i] == ymax: 
            jmax = i
            break
    xpeak = x[jmax]
    return (fwhm, xpeak, ymax, x_hpeak[0], x_hpeak[1])

def smooth(y, w, iterates=1):
    hw = 1 +  w/2
    my = scipy.array(y)
    for count in range(iterates):
        ys = my.copy()
        for i in range(0,hw):
            ys[i] = my[0:hw].mean()
        for i in range(len(y)-hw,len(y)):
            ys[i] = my[len(y)-hw:len(y)].mean()
        for i in range(hw,len(y)-hw):
            val=my[i-hw:i+hw].mean()
            ys[i] = val
        my = ys
    return ys

def anti_slope(x, y):
    ybl = y.copy()
    ybl[0] = y[0]
    for i in range(1,len(y)):
        ybl[i] = y[i] + ybl[i-1]
    return ybl

def get_baseline(x, y):
    return y - anti_slope(x, slopes(x,y))
    
def correct_baseline(x, y):
    return anti_slope(x, slopes(x,y))
