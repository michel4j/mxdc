import numpy
import scipy
import scipy.optimize

# Peak Function
# 0 = H - Height of peak
# 1 = L - FWHM of Voigt profile (Wertheim et al)
# 2 = P - Position of peak
# 3 = n - lorentzian fraction, gaussian/step offset


def step_func(x, coeffs):
    H, L, P = coeffs[:3]
    d = coeffs[3]
    y = abs(H)*( 0.5 + (1.0/numpy.pi)*scipy.arctan( (x-P)/(0.5*L))) + d
    return y

def multi_peak(x, coeffs, target='gaussian', fraction=0.5):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs)//4
    for i in range(npeaks):
        a, fwhm, pos, off = coeffs[i*4:(i+1)*4]
        n = fraction
        pars = [a, fwhm, pos, off, n]
        y += TARGET_FUNC[target](x,pars)
    return y

def multi_peak_fwhm(x, coeffs, fwhm, target='gaussian', fraction=0.5):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs)//3
    for i in range(npeaks):
        a, pos, off = coeffs[i*3:(i+1)*3]
        n = fraction
        pars = [a, fwhm, pos, off, n]
        y += TARGET_FUNC[target](x,pars)
    return y
        
def voigt(x, coeffs):
    H, L, P, O = coeffs[:4]
    n = min(1.0, max(0.0, coeffs[4]))
    lofr =  lorentz(x, coeffs[:4])
    gafr = gauss(x, coeffs[:4])   
    return n * lofr + (1.0-n)*gafr + O

def gauss(x, coeffs):
    H, L, P, O = coeffs[:4]
    sigma = L/2.35482
    return O + abs(H) * scipy.exp(-(x - P)**2/(2*sigma**2))

def lorentz(x, coeffs):
    H, L, P, O = coeffs[:4]
    return abs(H) * ((L/2.0)**2 / ((x-P)**2 + (L/2.0)**2)) + O

TARGET_FUNC = {
    'gaussian': gauss,
    'lorentzian': lorentz,
    'voigt': voigt,
    'step': step_func,
}

def peak_fit(x,y,target='gaussian'):
    """
    Returns the coefficients for the target function
     0 = H - Height of peak
     1 = L - FWHM of Voigt profile (Wertheim et al)
     2 = P - Position of peak
     3 = n - lorentzian fraction, gaussian offset
     
    Success (boolean)
    """
    if target != 'step':
        pars, success = histogram_fit(x,y)
        coeffs = [pars[0], pars[1], pars[2], 0, 0]
    else:
        coeffs = [1,1,0,0]
    
    def _err(p, x, y):
        vals = TARGET_FUNC[target](x,p)
        err=(vals-y)
        return err
    
    new_coeffs, cov_x, info, mesg, ier = scipy.optimize.leastsq(_err, coeffs[:], args=(x,y), maxfev=10000,full_output=1)
    if 1 <= ier <= 4:
        success = True
    else:
        success = False
    return new_coeffs, success

    
def histogram_fit(x,y):
    """
    calcfwhm(x,y) - with input x,y vector this function calculates fwhm and returns
    (fwhm,xpeak,ymax, fwhm_x_left, fwhm_x_right)
    x - input independent variable
    y - input dependent variable
    return ymax, fwhm, xpeak, x_hpeak[0], x_hpeak[1], cema
    cema is center of mass
    
    success boolean
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
    return [ymax, fwhm, xpeak, x_hpeak[0], x_hpeak[1], cema], True

