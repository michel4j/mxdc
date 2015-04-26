#!/bin/csh

## ---- Setup Top level directory of BCM installation ----
setenv MXDC_PATH /home/michel/Code/eclipse-ws/mxdc


## ---- Setup Beamline Configuration by network ----
setenv MXDC_BEAMLINE 08B1  # default beamline
set domain=`netstat -rn | grep '255.255.252.0' | awk '{print $1}'`
if ($domain == '10.52.28.0') then
	setenv MXDC_BEAMLINE 08ID
endif
if ($domain == '10.52.4.0') then
	setenv MXDC_BEAMLINE 08B1
endif
## ---- Do not change below this line ----
setenv MXDC_CONFIG_PATH $MXDC_PATH/etc
setenv MXDC_DATA_PATH  $HOME/scans
set path=($path $MXDC_PATH/bin)
if ($?PYTHONPATH) then
	setenv PYTHONPATH ${PYTHONPATH}:${MXDC_PATH}:${MXDC_PATH}/mxdc/libs
else
	setenv PYTHONPATH ${MXDC_PATH}:${MXDC_PATH}/mxdc/libs
endif
