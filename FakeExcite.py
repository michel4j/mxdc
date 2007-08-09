import scipy
from random import *

def gaussian(x, coeffs):
	return coeffs[0] * scipy.exp( - ( (x-coeffs[1])/coeffs[2] )**2 )


def gen_spectrum():
	x = scipy.linspace(0,4095,4096)
	y = scipy.zeros( [len(x)] )

	coeffs = [0,0,0]

	# generate peaks in spectrum
	for i in range(10):
		coeffs[0] = randint(3, 20)  # amplitude
		coeffs[1] = randint(20, 4070) # mean
		coeffs[2] = randint(15, 30) # sigma
		y += gaussian(x, coeffs) 
	# add some noise
	noise = 1
	y = y + noise*(scipy.rand(len(y))-0.5)
	return x,y
