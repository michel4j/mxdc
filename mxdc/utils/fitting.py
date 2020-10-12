import numpy
import scipy
from scipy import optimize, interpolate
from scipy.special import erf


# Peak Function
# 0 = H - Height of peak
# 1 = L - FWHM of Voigt profile (Wertheim et al)
# 2 = P - Position of peak
# 3 = n - lorentzian fraction, gaussian/step offset


def step_func(x, coeffs):
    H, L, P = coeffs[:3]
    d = coeffs[3]
    y = 0.5 * H * (0.5 + (1.0 / numpy.pi) * scipy.arctan((x - P) / (0.5 * L))) + d
    return y


def step(x, coeffs):
    H, W, P = coeffs[:3]
    return H * 0.5 * (1 + erf((x - P) / (W * numpy.sqrt(2))))


def step_response(x, coeffs):
    H, L, P = coeffs[:3]
    p = 1
    mu = 6
    y = numpy.zeros_like(x)
    xc = (x - P) / L
    xe = xc[xc >= 0.1]
    theta = numpy.pi / 3
    y[xc >= 0.1] = (H * (1 - numpy.exp(-p * (xe)) * numpy.sin(mu * (xe) + theta) / numpy.sin(theta)) / numpy.sqrt(2))
    return y


def multi_peak(x, coeffs, target='gaussian', fraction=0.5):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs) // 4
    for i in range(npeaks):
        a, fwhm, pos, off = coeffs[i * 4:(i + 1) * 4]
        n = fraction
        pars = [a, fwhm, pos, off, n]
        y += TARGET_FUNC[target](x, pars)
    return y


def multi_peak_simple(x, coeffs):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs) // 2 - 1
    fwhm = coeffs[-2]
    off = coeffs[-1]
    for i in range(npeaks):
        a, pos = coeffs[i * 2:(i + 1) * 2]
        pars = [a, fwhm, pos, off, 0.25]
        y += voigt(x, pars)
    return y


def multi_peak_fwhm(x, coeffs, fwhm, target='gaussian', fraction=0.5):
    y = numpy.zeros(len(x))
    npeaks = len(coeffs) // 3
    for i in range(npeaks):
        a, pos, off = coeffs[i * 3:(i + 1) * 3]
        n = fraction
        pars = [a, fwhm, pos, off, n]
        y += TARGET_FUNC[target](x, pars)
    return y


def voigt(x, coeffs):
    H, L, P, O = coeffs[:4]
    n = min(1.0, max(0.0, coeffs[4]))
    lofr = lorentz(x, coeffs[:4])
    gafr = gauss(x, coeffs[:4])
    return n * lofr + (1.0 - n) * gafr + O


def gauss(x, coeffs):
    H, L, P, O = coeffs[:4]
    sigma = L / 2.35482
    return O + abs(H) * scipy.exp(-(x - P) ** 2 / (2 * sigma ** 2))


def lorentz(x, coeffs):
    H, L, P, O = coeffs[:4]
    return abs(H) * ((L / 2.0) ** 2 / ((x - P) ** 2 + (L / 2.0) ** 2)) + O


def decay_func(x, coeffs):
    A, B, O = coeffs[:3]
    return O + A * numpy.exp(-B * x)


TARGET_FUNC = {
    'gaussian': gauss,
    'lorentz': lorentz,
    'voigt': voigt,
    'step': step_func,
    'decay': decay_func,
    'multi_peak_simple': multi_peak_simple,
}


class PeakFitter(object):
    def __init__(self, default=(1., 1., 0., 0.)):
        self.success = False
        self.default = default

    def __call__(self, x, y, target="gaussian"):
        if type(target) == str:
            target_func = TARGET_FUNC[target]
        else:
            target_func = target

        if target in ['gaussian', 'voigt', 'lorentz']:
            pars, success = histogram_fit(x, y)
            coeffs = [pars[0], pars[1], pars[2], 0, 0]
        else:
            coeffs = self.default

        def _err(p, x, y):
            vals = target_func(x, p)
            err = (y - vals)
            return err

        new_coeffs, cov_x, info, mesg, ier = optimize.leastsq(_err, coeffs[:], args=(x, y), maxfev=10000, full_output=1)
        if 1 <= ier <= 4:
            success = True
        else:
            success = False

        self.success = success
        self.coeffs = new_coeffs
        self.cov = cov_x
        self.info = info
        self.msg = mesg
        self.ier = ier
        self.residual = (_err(self.coeffs, x, y) ** 2).sum()
        self.ycalc = target_func(x, self.coeffs)

        return new_coeffs, success


def peak_fit(x, y, target='gaussian'):
    """
    Returns the coefficients for the target function
     0 = H - Height of peak
     1 = L - FWHM of Voigt profile (Wertheim et al)
     2 = P - Position of peak
     3 = n - lorentzian fraction, gaussian offset
     
    Success (boolean)
    """
    if target != 'step':
        pars, success = histogram_fit(x, y)
        coeffs = [pars[0], pars[1], pars[2], 0, 0]
    else:
        coeffs = [1, 1, 0, 0]

    def _err(p, x, y):
        vals = TARGET_FUNC[target](x, p)
        err = (vals - y)
        return err

    new_coeffs, cov_x, info, mesg, ier = optimize.leastsq(_err, coeffs[:], args=(x, y), maxfev=10000, full_output=1)
    if 1 <= ier <= 4:
        success = True
    else:
        success = False
    return new_coeffs, success


def histogram_fit(xo, yo):
    """
    calcfwhm(x,y) - with input x,y vector this function calculates fwhm and returns
    (fwhm,xpeak,ymax, fwhm_x_left, fwhm_x_right)
    x - input independent variable
    y - input dependent variable
    return ymax, fwhm, xpeak, fwhm_left, fwhm_right, cema
    cema is center of mass
    
    success boolean
    """

    yfunc = interpolate.interp1d(xo, yo, bounds_error=False, fill_value=0.0)
    x = numpy.linspace(min(xo), max(xo), 1000)
    y = yfunc(x)

    ymin, ymax = min(y), max(y)
    y_hpeak = ymin + .5 * (ymax - ymin)
    yhm = numpy.where(y > y_hpeak)[0]

    i_max = numpy.argmax(y)
    if numpy.any(yhm):
        i_start = yhm[0]
        i_end = yhm[-1]
        fwhm = max(x[i_end] - x[i_start], 2*(x[i_end] - x[i_max]), 2*(x[i_max] - x[i_start]))
    else:
        i_start = 0
        i_end = len(x)-1
        i_max = i_end//2
        fwhm = x[i_end] - x[i_start]

    xpeak = x[i_max]
    fwhm_x_left = x[i_start]
    fwhm_x_right = x[i_end]
    cema = (x * y).sum() / y.sum()

    return [ymax, fwhm, xpeak, fwhm_x_left, fwhm_x_right, cema], True


class SplineRep(object):
    def __init__(self, x, y):
        self.fit = None
        self.fit = interpolate.splrep(x, y)

    def __call__(self, x):
        return interpolate.splev(x, self.fit, der=0)
