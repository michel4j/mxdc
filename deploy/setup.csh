#!/bin/csh

## ---- Beamline Configuration File ----
setenv BCM_CONFIG_FILE 08b1.conf

## ---- Top level directory of BCM installation ----
setenv BCM_PATH /home/michel/Code/eclipse-ws/beamline-control-module
#setenv BCM_PATH /media/seagate/beamline-control-module


## ---- Do not change below this line ----
setenv BCM_CONFIG_PATH $BCM_PATH/etc
setenv BCM_DATA_PATH  $BCM_PATH/etc
set path=($path $BCM_PATH/bin)
if ($?PYTHONPATH) then
	setenv PYTHONPATH ${PYTHONPATH}:${BCM_PATH}
else
	setenv PYTHONPATH ${BCM_PATH}
endif
