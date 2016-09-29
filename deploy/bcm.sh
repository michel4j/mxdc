#!/bin/sh

## ---- Setup Top level directory of BCM installation ----
export BCM_PATH=/home/michel/Code/eclipse-ws/mxdc


## ---- Setup Beamline Configuration by network ----

if [ ! -z "$BCM_FORCE" ]; then
    export BCM_BEAMLINE=$BCM_FORCE
    export BCM_S111_TEMP=LN2
else 

    export BCM_BEAMLINE=08B1  # default beamline
    domain=`netstat -rn | grep '255.255.252.0' | awk '{print $1}'`
    if [ $domain = '10.52.28.0' ] ; then
	    export BCM_BEAMLINE=08ID
	    export BCM_S111_TEMP=LN2
    fi

    if [ $domain = '10.52.4.0' ] ; then
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

