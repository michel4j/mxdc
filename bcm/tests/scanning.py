#!/usr/bin/env python
import sys, time

from Beamline import beamline
from Scanner import Scanner
myscan = Scanner()
mca = beamline['detectors']['mca']
motor = beamline['motors']['energy']

myscan(motor, 10,11,60,mca,0.5)
midp, fwhm, success = myscan.fit()
if success:
    print "MIDP: %8g    FWHM: %8g" % ( midp, fwhm)
else:
    print "Could not fit gausian"

