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
    
    def _err(p, y, x):
        vals = TARGET_FUNC[target](x,p)
        err=(y-vals)
        return err
    
    new_coeffs, results = scipy.optimize.leastsq(_err, coeffs[:], args=(x,y))
    return new_coeffs

    
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
    return [ymax, fwhm, xpeak, 0]


def savitzky_golay(data, kernel = 11, order = 4):
    """
        applies a Savitzky-Golay filter
        input parameters:
        - data => data as a 1D numpy array
        - kernel => a positiv integer > 2*order giving the kernel size
        - order => order of the polynomal
        returns smoothed data as a numpy array

        invoke like:
        smoothed = savitzky_golay(<rough>, [kernel = value], [order = value]
    """
    try:
            kernel = abs(int(kernel))
            order = abs(int(order))
    except ValueError, msg:
        raise ValueError("kernel and order have to be of type int (floats will be converted).")
    if kernel % 2 != 1 or kernel < 1:
        raise TypeError("kernel size must be a positive odd number, was: %d" % kernel)
    if kernel < order + 2:
        raise TypeError("kernel is to small for the polynomals\nshould be > order + 2")

    # a second order polynomal has 3 coefficients
    order_range = range(order+1)
    half_window = (kernel -1) // 2
    b = numpy.mat([[k**i for i in order_range] for k in range(-half_window, half_window+1)])
    # since we don't want the derivative, else choose [1] or [2], respectively
    m = numpy.linalg.pinv(b).A[0]
    window_size = len(m)
    half_window = (window_size-1) // 2

    # precompute the offset values for better performance
    offsets = range(-half_window, half_window+1)
    offset_data = zip(offsets, m)

    smooth_data = list()

    ## temporary data, with padded zeros (since we want the same length after smoothing)
    #data = numpy.concatenate((numpy.zeros(half_window), data, numpy.zeros(half_window)))
    
    # temporary data, with padded first/last values (since we want the same length after smoothing)
    firstval=data[0]
    lastval=data[len(data)-1]
    data = numpy.concatenate((numpy.zeros(half_window)+firstval, data, numpy.zeros(half_window)+lastval))
    
    for i in range(half_window, len(data) - half_window):
            value = 0.0
            for offset, weight in offset_data:
                value += weight * data[i + offset]
            smooth_data.append(value)
    return numpy.array(smooth_data)
