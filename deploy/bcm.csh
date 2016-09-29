#!/bin/csh

## ---- Setup Top level directory of BCM installation ----
setenv BCM_PATH /home/michel/Code/eclipse-ws/mxdc


## ---- Setup Beamline Configuration by network ----
setenv BCM_BEAMLINE 08B1  # default beamline

set osver=`cat /etc/redhat-release|awk '{print $4}' | cut -c1 `
if ("$osver" == '6') then
   set domain=`netstat -rn | grep 'UG' | awk '{print $2}'`
else
   set domain=`netstat -rn | grep 'UGH' | awk '{print $2}'`
endif
if ($domain == '10.52.31.254') then
	setenv BCM_BEAMLINE 08ID
	setenv BCM_S111_TEMP LN2
endif
if ($domain == '10.52.7.25') then
	setenv BCM_BEAMLINE 08B1
	setenv BCM_S111_TEMP RT
endif

## ---- Do not change below this line ----
setenv BCM_CONFIG_PATH $BCM_PATH/etc
setenv BCM_DATA_PATH  $HOME/scans
set path=($path $BCM_PATH/bin)
if ($?PYTHONPATH) then
	setenv PYTHONPATH ${PYTHONPATH}:${BCM_PATH}:${BCM_PATH}/bcm/libs
else
	setenv PYTHONPATH ${BCM_PATH}:${BCM_PATH}/bcm/libs
endif
