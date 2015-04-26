#!/bin/sh

## ---- Setup Top level directory of BCM installation ----
export MXDC_PATH=/home/michel/Code/eclipse-ws/mxdc


## ---- Setup Beamline Configuration by network ----
export MXDC_BEAMLINE=08B1  # default beamline
domain=`netstat -rn | grep '255.255.252.0' | awk '{print $1}'`
if [ $domain = '10.52.28.0' ] ; then
	export MXDC_BEAMLINE=08ID
fi

if [ $domain = '10.52.4.0' ] ; then
	export MXDC_BEAMLINE=08B1
fi

## ---- Do not change below this line ----
export MXDC_CONFIG_PATH=$MXDC_PATH/etc
export MXDC_DATA_PATH=$HOME/scans
export PATH=${PATH}:$MXDC_PATH/bin
if [ $PYTHONPATH ]; then
	export PYTHONPATH=${PYTHONPATH}:${MXDC_PATH}:${MXDC_PATH}/mxdc/libs
else
	export PYTHONPATH=${MXDC_PATH}:${MXDC_PATH}/mxdc/libs
fi

