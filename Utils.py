import gtk, gobject
import os
import numpy, time

# Physical Constats
h = 4.13566733e-15 # eV.s
c = 299792458e10   # A/s
#S111_a = 5.4310209 # A at RT
S111_a  = 5.4297575 # A at LN2 

def check_directory(directory, parent=None):
    if not os.path.exists(directory):
        message  = "Directory '%s' does not exist!\n" % directory
        message += "Please enter a valid directory or create one."
        dialog = gtk.MessageDialog(parent, gtk.DIALOG_DESTROY_WITH_PARENT,
            gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE,
            message)
        if dialog.run() == gtk.RESPONSE_CLOSE:
            dialog.destroy()
        return False
    elif not os.access(directory,os.W_OK):
        message  = "You do not have write access to '%s'!\n" % directory
        message += "Please enter a valid directory or create one."
        dialog = gtk.MessageDialog(parent, gtk.DIALOG_DESTROY_WITH_PARENT,
            gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE,
            message)
        if dialog.run() == gtk.RESPONSE_CLOSE:
            dialog.destroy()
        return False
    return True
    
def select_folder(default):
	"""This function is used to browse for a Folder.
	The path to the folder will be returned if the user
	selects one, however a blank string will be returned
	if they cancel or do not select one."""
	
	file_open = gtk.FileChooserDialog(title="Select Image"
		, action=gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
		, buttons=(gtk.STOCK_CANCEL
				, gtk.RESPONSE_CANCEL
				, gtk.STOCK_OPEN
				, gtk.RESPONSE_OK))
	"""Create and add the Images filter"""	
	file_open.set_uri('file:/%s' % default)
	result = None
	if file_open.run() == gtk.RESPONSE_OK:
		result = file_open.get_filename()
	file_open.destroy()
	
	return result

def keV_to_A(energy): #Angstroms
	return (h*c)/(energy*1000.0)

def A_to_keV(wavelength): #eV
	return (h*c)/(wavelength*1000.0)

def radians(angle):
    return numpy.pi * angle / 180.0

def degrees(angle):
    return 180 * angle / numpy.pi

def bragg_to_keV(bragg):
    d = S111_a / numpy.sqrt(3.0)
    wavelength = 2.0 * d * numpy.sin( radians(bragg) )
    return A_to_keV(wavelength)

def keV_to_bragg(energy):
    d = S111_a / numpy.sqrt(3.0)
    bragg = numpy.arcsin( keV_to_A(energy)/(2.0*d) )
    return degrees(bragg)

def dec2bin(x):
    return x and (dec2bin(x/2) + str(x%2)) or '0'
    
