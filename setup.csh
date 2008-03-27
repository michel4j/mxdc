#!/bin/csh

# Set BCM_PATH to the top-level directory containing the BCM modules

setenv BCM_PATH /home/michel/Workspace/mxdc-bcm
setenv BCM_CONFIG_PATH $BCM_PATH/bcm/config
setenv BCM_BEAMLINE 08id1

set path=($path $BCM_PATH)

