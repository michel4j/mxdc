#!/bin/sh

## ---- Setup Top level directory of BCM installation ----
export BCM_PATH=/home/michel/Code/eclipse-ws/beamline-control-module


## ---- Setup Beamline Configuration by network ----
export BCM_BEAMLINE=08b1  # default beamline
domain=`netstat -rn | grep '255.255.252.0' | awk '{print $1}'`
if [ $domain = '10.52.28.0' ] ; then
	export BCM_BEAMLINE=08id1
	export BCM_S111_TEMP=LN2
fi

if [ $domain = '10.52.4.0' ] ; then
	export BCM_BEAMLINE=08b1
	export BCM_S111_TEMP=RT
fi

## ---- Do not change below this line ----
export BCM_CONFIG_FILE=${BCM_BEAMLINE}.conf
export BCM_CONSOLE_CONFIG_FILE=${BCM_BEAMLINE}-console.conf
export BCM_CONFIG_PATH=$BCM_PATH/etc
export BCM_DATA_PATH=$HOME/scans
export PATH=${PATH}:$BCM_PATH/bin
if [ $PYTHONPATH ]; then
	export PYTHONPATH=${PYTHONPATH}:${BCM_PATH}
else
	export PYTHONPATH=${BCM_PATH}
fi

# Setup MOZEMBED XUL PATH
gre_version=`xulrunner --gre-version`
xul_lib=`xulrunner --find-gre ${gre_version}`
if [ ! $MOZILLA_FIVE_HOME ]; then
	export MOZILLA_FIVE_HOME=`dirname ${xul_lib}`
fi
