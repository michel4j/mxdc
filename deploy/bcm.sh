#!/bin/sh

## ---- Setup Top level directory of BCM installation ----
export BCM_PATH=/home/michel/Code/Projects/mxdc


## ---- Setup Beamline Configuration by network ----

if [ ! -z "$BCM_FORCE" ]; then
    export BCM_BEAMLINE=$BCM_FORCE
    export BCM_S111_TEMP=LN2
else

    export BCM_BEAMLINE=08B1  # default beamline
    osver=`cat /etc/redhat-release|awk '{print $4}' | cut -c1 `
    if [ "$osver" = "6" ] ; then
       domain=`netstat -rn | grep 'UG' | awk '{print $2}'`
    else
       domain=`netstat -rn | grep 'UGH' | awk '{print $2}'`
    fi

    if [ "$domain" = '10.52.31.254' ] ; then
        export BCM_BEAMLINE=08ID
        export BCM_S111_TEMP=LN2
    fi

    if [ "$domain" = '10.52.7.254' ] ; then
        export BCM_BEAMLINE=08B1
        export BCM_S111_TEMP=RT
    fi

fi

## ---- Do not change below this line ----
export BCM_CONFIG_PATH=$BCM_PATH/etc
export BCM_DATA_PATH=$HOME/scans
export PATH=${PATH}:$BCM_PATH/bin
if [ $PYTHONPATH ]; then
	export PYTHONPATH=${PYTHONPATH}:${BCM_PATH}:${BCM_PATH}/bcm/libs
else
	export PYTHONPATH=${BCM_PATH}:${BCM_PATH}/bcm/libs
fi

