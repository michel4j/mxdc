#!/usr/bin/env python

import sys, os
sys.path += ['../']

from Detectors import *

mca = EpicsMCA('XFD1608-101:mca1')
mca.setup(roi=(0,100))
counts = mca.count(5)
print "5 seconds channels 0-100:", counts
mca.configure(roi=None)
data = mca.count(10)
print "total channels:", len(data)

from pylab import *
plot(data)
show()
