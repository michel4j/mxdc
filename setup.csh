#!/bin/csh

# Set BCM_PATH to the top-level directory containing the BCM modules

setenv BCM_PATH /users/cmcfadmin/michel/bcm-sandbox

setenv BCM_CONFIG_PATH $BCM_PATH/bcm/config
setenv BCM_DATA_PATH  $BCM_PATH/bcm/data
setenv BCM_BEAMLINE 08id1

set path=($path $BCM_PATH)

