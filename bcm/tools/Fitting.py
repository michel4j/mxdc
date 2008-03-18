#!/usr/bin/env python
from scipy import optimize, array, exp
from random import *
 
def res(p, y, x):
    vals = gaus(x,p)
    err=(y-vals)
    return err

def gaus(x,p):
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


def gauss_fit(x,y):
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
    pars = calcfwhm(x,y)
    p0= [pars[2], pars[1],pars[0]/2.35,0.0]
    p1,lsqres=optimize.leastsq(res, p0, args=(y,x))
    return p1, lsqres

def calcfwhm(x,y):
    """
    calcfwhm(x,y) - with input x,y vector this function calculates fwhm and returns
    (fwhm,xpeak,ymax)
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
    return (fwhm,xpeak,ymax, x_hpeak[0], x_hpeak[1])

