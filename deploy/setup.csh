#!/bin/csh

# Set BCM_PATH to the top-level directory containing the BCM module

setenv BCM_PATH /opt/cmcf_apps/bcm
setenv BCM_CONFIG_PATH $BCM_PATH/bcm/config
setenv BCM_DATA_PATH  $BCM_PATH/bcm/data
setenv BCM_BEAMLINE 08id1

set path=($path $BCM_PATH)
alias mxdc 'python $BCM_PATH/mxdc/mxdcapp.py'
