#!/usr/bin/env python

from Beamline import beamline

def prepare_for_mounting():
    safe_distance = 500
    safe_beamstop = 49
    beamline['motors']['detector_dist'].move_to(safe_distance, wait=True)
    beamline['motors']['bst_z'].move_to(safe_beamstop, wait=True)
    return True

def restore_beamstop():
    distance = 300
    beamstop = 1
    beamline['motors']['bst_z'].move_to(beamstop, wait=True)
    beamline['motors']['detector_dist'].move_to(distance, wait=True)
    return True
