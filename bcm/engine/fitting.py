import numpy
import scipy

# Peak Function
# 0 = H - Height of peak
# 1 = L - FWHM of Voigt profile (Wertheim et al)
# 2 = P - Position of peak
# 3 = n - lorentzian fraction


def step(x, coeffs):
    H, L, P = coeffs[:3]
    d = coeffs[3]
    y = abs(H)*( 0.5 + (1.0/pi)*scipy.arctan( (x-P)/(0.5*L)))
    def _mod_step(x):
        return (x > P) and scipy.exp(-d * (x-P-L)) or (x <= P) and 1.0
        
    yexp = map(_mod_step, x)
    y = y*yexp
    return y-min(y)

def multi_peak(x, coeffs, target='gaussian'):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs)//3
    for i in range(npeaks):
        a, fwhm, pos = coeffs[i*3:(i+1)*3]
        n = 0.5
        pars = [a, fwhm, pos, n]
        y += TARGET_FUNC[target](x,pars)
    return y
        
def voigt(x, coeffs):
    H, L, P = coeffs[:3]
    n = min(1.0, max(0.0, coeffs[3]))
    lofr =  lorentz(x, coeffs[:3])
    gafr = gauss(x, coeffs[:3])   
    return n * lofr + (1.0-n)*gafr

def gauss(x, coeffs):
    H, L, P = coeffs[:3]
    c = 2.35482
    return abs(H) * scipy.exp(-0.5*(( x - P)/(L/c))**2 )

def lorentz(x, coeffs):
    H, L, P = coeffs[:3]
    return abs(H) * ((L/2.0)**2 / ((x-P)**2 + (L/2.0)**2))

TARGET_FUNC = {
    'gaussian': gauss,
    'lorentzian': lorentz,
    'voigt': voigt,
    'step': step,
}

def peak_fit(x,y,target='gaussian'):
    coeffs = [1, 1, 0, 0.5]
    
    def _err(p, x, y):
        vals = TARGET_FUNC[target](x,p)
        err=(y-vals)
        return err
    
    new_coeffs, results = scipy.optimize.leastsq(_err, coeffs[:], args=(x,y), maxfev=10000)
    return new_coeffs

    
def histogram_fit(x,y):
    """
    calcfwhm(x,y) - with input x,y vector this function calculates fwhm and returns
    (fwhm,xpeak,ymax, fwhm_x_left, fwhm_x_right)
    x - input independent variable
    y - input dependent variable
    fwhm - return full width half maximum
    xpeak - return x value at midpoint
    cema - center of mass
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
    #xpeak = x[jmax]
    xpeak = (x_hpeak_r + x_hpeak_l)/2.0
    cema = sum(x*y)/sum(y)
    return [ymax, fwhm, xpeak, cema]

