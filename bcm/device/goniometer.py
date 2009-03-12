import time
import logging
import warnings
warnings.simplefilter("ignore")

from zope.interface import implements
from bcm.device.interfaces import IGoniometer
from bcm.protocol.ca import PV
from bcm.device.motor import VMEMotor
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Goniometer state constants
(
    GONIO_IDLE,
    GONIO_ACTIVE,
) = range(2)

class GoniometerError(Exception):

    """Base class for errors in the goniometer module."""

class Goniometer(object):

    implements(IGoniometer)

    def __init__(self, name):
        self.name = name
        pv_root = name.split(':')[0]
        # initialize process variables
        self._scan_cmd = PV("%s:scanFrame.PROC" % pv_root, monitor=False)
        self._state = PV("%s:scanFrame:status" % pv_root)
        self._shutter_state = PV("%s:outp1:fbk" % pv_root)
        
        self.omega = VMEMotor('%s:deg' % name)
                
        #parameters
        self._settings = {
            'time' : PV("%s:expTime" % pv_root, monitor=False),
            'delta' : PV("%s:deltaOmega" % pv_root, monitor=False),
            'angle': PV("%s:openSHPos" % pv_root, monitor=False),
        }
        
                
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def scan(self, wait=True):
        self._scan_cmd.set('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def get_state(self):
        return self._state.get() != 0   
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        pass    # FIXME: We need a proper way to stop goniometer scan


class MD2Goniometer(object):

    implements(IGoniometer)

    def __init__(self, name):
        self.name = name
        pv_root = name
        # initialize process variables
        self._scan_cmd = PV("%s:S:StartScan" % pv_root, monitor=False)
        self._abort_cmd = PV("%s:S:AbortScan" % pv_root, monitor=False)
        self._state = PV("%s:G:MachAppState" % pv_root)
        self._shutter_state = PV("%s:G:ShutterIsOpen" % pv_root)
        self._log = PV('%s:G:StatusMsg' % pv_root)
        
        self.omega = VMEMotor('%s:G:OmegaPosn' % pv_root)
                
        #parameters
        self._settings = {
            'time' : PV("%s:S:ScanExposureTime" % pv_root, monitor=False),
            'delta' : PV("%s:S:ScanRange" % pv_root, monitor=False),
            'angle': PV("%s:S:ScanStartAngle" % pv_root, monitor=False),
            'passes': PV("%s:S:ScanNumOfPasses" % pv_root, monitor=False),
        }
                       
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def scan(self):
        self._scan_cmd.set(1)

    def get_state(self):
        return self._state.get() != 3  
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        self._abort_cmd.set(1)

""" MD2 HELP
Most Popular Feedback PV's

BL08B1:MD2:enabled
This PV contains the status of the MD2, the MD2 will be in the "Enabled" state if:

*There is currently no error being reported by the MD2 hardware
*There is currently no error being reported by the MD2 Software
*The current state of the MD2 is that is is NOT performing another task which is the same as saying the next point
*The current state of the software (see BL08B1:MD2:G:MachAppState) indicates that the MD2 is in "STANDBY"

The PV will be "Disabled" if

*any one or all of the conditions above are NOT met. 
When the state is "Disabled" all feedback PV's will still read feedback from the MD2 but all PV outputs TO the MD2 (with the exception of RESET) will be  disabled, the outputs will be renabled when staff has determined the problem and re enabled the MD2.

BL08B1:MD2:G:MachAppState
This PV contains the status of the MD2 Hardware, it is defined in Epics as the following:
record(mbbi, "$(clsName):G:MachAppState") {
 field(DTYP, "Raw Soft Channel")
 field( ZRVL, "0") field( ZRST, "FAULT")       # hardware error
 field( ONVL, "1") field( ONST, "ALARM")       # the computing of the centring position failed
 field( TWVL, "2") field( TWST, "INIT")        # init pending
 field( THVL, "3") field( THST, "STANDBY")     # ready to accept a command
 field( FRVL, "4") field( FRST, "MOVING")      # the app is processing a command. 
 field( FVVL, "5") field( FVST, "RUNNING")     # waiting a user action to complete a remote command
 field( SXVL, "6") field( SXST, "CLOSING")     # aplication is closing devices to shut down. No more state changes are allowed
 field( SVVL, "7") field( SVST, "UNDEFINED")   # Unininitialized variables state
}

BL08B1:MD2:G:ProcessInfo
This PV contains the status of the MD2 Software Application, it is defined in Epics as the following:
record(mbbi, "$(clsName):G:ProcessInfo") {
 field(INP,      "$(clsName):G:ProcessInfo:scal CP")
 field( ZRVL, "0") field( ZRST, "Running")     # Busy
 field( ONVL, "1") field( ONST, "SUCCESS")     # Everything went well
 field( TWVL, "2") field( TWST, "ALARM")       # An Alarm has occurred
 field( THVL, "3") field( THST, "FAULT")       # Hardware Fault
}

BL08B1:MD2:G:StatusMsg
This PV contains the current message string that is to be displayed to the user, it matched the message that si displayed on the MD2 GUI.
record(waveform, "$(clsName):G:StatusMsg")
{
 field(DESC, "StatusMessage")
 field(INP, "$(clsName):G:StatusMsg:asyn.BINP CP")
 field(NELM,"256") #880 is the max characters
 field(FTVL,"CHAR")
}

BL08B1:MD2:G:ProcessInfo
This PV contains the status of the MD2 Software Application, it is defined in Epics as the following:
record(mbbi, "$(clsName):G:ProcessInfo") {
 field(INP,      "$(clsName):G:ProcessInfo:scal CP")
 field( ZRVL, "0") field( ZRST, "Running")     # Busy
 field( ONVL, "1") field( ONST, "SUCCESS")     # Everything went well
 field( TWVL, "2") field( TWST, "ALARM")       # An Alarm has occurred
 field( THVL, "3") field( THST, "FAULT")       # Hardware Fault
}

[edit]
Other useful feedbacks
[edit]
Binary feedback (on.off)

BL08B1:MD2:G:SampleMagnetIsOn

1 = The MD2 smart magnet is currently energized
0 = it is not energized

BL08B1:MD2:G:SampleIsLoaded

This PV maybe redundant, use BL08B1:MD2:G:SampleIsDetected instead
1 = The MD2 smart magnet detects that there is a xtal pin currently sitting on the end of the goniometer
0 = it doesn't detect one

BL08B1:MD2:G:SampleIsCentred

1 = The mounted sample has been centered
0 = it has not been centered yet

BL08B1:MD2:G:SampleIsAligned

1 = Not sure yet exactly what this means when its on or off
0 = TBD

BL08B1:MD2:G:BeamIsLocated

1 = Not sure yet exactly what this means when its on or off
0 = TBD

BL08B1:MD2:G:SampleIsDetected

1 = The MD2 smart magnet detects that there is a xtal pin currently sitting on the end of the goniometer
0 = it doesn't detect one

[edit]
Data Scan Parameters

To have the MD2 scan (it controls the shutter) a frame of data (not including the detector control) you must write to the following 4 PV's then push any value to the PV BL08B1:MD2:S:StartScan to start the scan:

1)BL08B1:MD2:S:ScanStartAngle
 DESCRIPTION: This is the Scan Start Angle PV. 
 UNIT: degrees.

2)BL08B1:MD2:S:ScanRange
 DESCRIPTION: This is the Scan Range or delta omega PV.
 UNIT: degrees.

3)BL08B1:MD2:S:ScanExposureTime
 DESCRIPTION: This is the Exposure Time PV. 
 UNIT: seconds.

4)BL08B1:MD2:S:ScanNumOfPasses
 DESCRIPTION: This is the number of times to repeat the defined scan PV. 
 UNIT: Number of times to rotate over the Scan Range, each time being a duration of Exposure Time
  example: given 
   BL08B1:MD2:S:ScanStartAngle   = 95.5
   BL08B1:MD2:S:ScanRange        = 2.5
   BL08B1:MD2:S:ScanExposureTime = 10
     
   if BL08B1:MD2:S:ScanNumOfPasses = 1 the data frame will consists of a rotation from:
     95.0deg  to (95.0 + 2.5)deg = total exposure time  = (Exposure Time *  ScanNumOfPasses) = 10 seconds
   if BL08B1:MD2:S:ScanNumOfPasses = 2 the rotation will be:
     95.0deg to (95.0 + 2.5)deg then back to down to 95.0deg = total exposure time = (Exposure Time *  ScanNumOfPasses) = 20 seconds
   values of BL08B1:MD2:S:ScanNumOfPasses greater than 2 continue extending the same sequence as outlined above
"""
