#!/bin/csh

## ---- Setup Top level directory of BCM installation ----
setenv BCM_PATH /home/michel/Code/eclipse-ws/beamline-control-module


## ---- Setup Beamline Configuration by network ----
setenv BCM_BEAMLINE 08b1  # default beamline
set domain=`netstat -rn | grep '255.255.252.0' | awk '{print $1}'`
if ($domain == '10.52.28.0') then
	setenv BCM_BEAMLINE 08id1
	setenv BCM_S111_TEMP LN2
endif
if ($domain == '10.52.4.0') then
	setenv BCM_BEAMLINE 08b1
	setenv BCM_S111_TEMP RT
endif
## ---- Do not change below this line ----
setenv BCM_CONFIG_FILE ${BCM_BEAMLINE}.conf
setenv BCM_CONSOLE_CONFIG_FILE ${BCM_BEAMLINE}-console.conf
setenv BCM_CONFIG_PATH $BCM_PATH/etc
setenv BCM_DATA_PATH  $HOME/scans
set path=($path $BCM_PATH/bin)
if ($?PYTHONPATH) then
	setenv PYTHONPATH ${PYTHONPATH}:${BCM_PATH}
else
	setenv PYTHONPATH ${BCM_PATH}
endif
