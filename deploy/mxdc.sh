#!/bin/sh

## ---- Setup Top level directory of BCM installation ----
export MXDC_PATH=/home/michel/Code/Projects/mxdc


## ---- Setup Beamline Configuration by network ----
if [ ! -z "$MXDC_FORCE" ]; then
    export MXDC_BEAMLINE=$MXDC_FORCE
else
    export MXDC_BEAMLINE=08B1  # default beamline
    osver=`cat /etc/redhat-release|awk '{print $4}' | cut -c1 `
    if [ "$osver" = "6" ] ; then
       domain=`netstat -rn | grep 'UG' | awk '{print $2}'`
    else
       domain=`netstat -rn | grep 'UGH' | awk '{print $2}'`
    fi

    if [ "$domain" = '10.52.31.254' ] ; then
        export MXDC_BEAMLINE=08ID
    fi

    if [ "$domain" = '10.52.7.254' ] ; then
        export MXDC_BEAMLINE=08B1
    fi
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

