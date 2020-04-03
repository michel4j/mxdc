Installation
============

It is recommended to install MxDC within a python virtual environment. MxDC can be installed using the python setup
tools from within the top-level directory of the application as follows.

.. code-block:: bash

    python3 -m venv venv
    source venv/bin/activate
    python setup.py install


This will install all MxDC and all it's dependences in the python environment.


Configuration
=============

MxDC needs a beamline configuration file to be able to perform the most basic control operations or run any of the
included programs.  The configuration file is a special python module placed in a specific directory defined
by the MXDC_CONFIG environment variable.

An example configuration file `CONFIG_example.py` is available within the `deploy/` sub-directory of distribution
archive. Copy this file to the directory pointed to by MXDC_CONFIG and modify as needed.  The name of the file is
not important except it must be named such that it is a valid python module.  The MXDC_CONFIG directory may
contain as many beamline configuration files as desired.

The general philosophy for a configuration file is that you would typically import your device  and service
classes at the top of the module, and then create instances of the devices in the configuration sections.  The following
configuration sections are expected in configuration files.

.. rubric:: CONFIG

A python dictionary specifying various configuration parameters for the beamline. Parameters defined in
this section will be available through the `beamline.config` attribute of beamline objects. Only a few of these parameters
are mandatory but there is no limit on which parameters can be defined.

.. topic:: Required Parameters for all Beamlines

    * name - The acronym of the beamline
    * facility - The acronym of the synchrotron facility
    * mono - The type of monochromator (eg 'Si 111')
    * mono_unit_cell - The monochromator unit cell length
    * source - The name of the beam source
    * type - The full module name of the beamline class as a string, e.g 'mxdc.beamlines.mx.MXBeamline'
    * subnet - The beamline subnet, e.g. '10.52.4.0/22'

.. rubric:: Example:

.. code-block:: python

    CONFIG = {
        'name': 'SIM-1',
        'facility': 'CLS',
        'mono': 'Si 111',
        'mono_unit_cell': 5.4297575,
        'source': 'CLS Sim SGU',
        'type': 'mxdc.beamlines.mx.MXBeamline',
        'subnet': '10.12.1.0/22',
        ...
    }


.. rubric:: DEVICES

A python dictionary mapping device names to device instances. The only restriction for device names is
that they should be valid python attribute names since they will be available as attributes of the beamline instance.
Additionally, each beamline class may define required devices that must be provided in configuration files for instances
of that beamline.

.. rubric:: Example:

.. code-block:: python


    from mxdc.devices import motor, goniometer

    DEVICES = {
        ...
        'manager': manager.SimModeManager(),
        'goniometer': goniometer.SimGonio(),
        'omega': motor.SimMotor('Omega', 0.0, 'deg', speed=60.0, precision=3),
        'sample_x': motor.SimMotor('Sample X', 0.0, units='mm', speed=0.2),
        'sample_y1': motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),
        'sample_y2': motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),
        ...
    }


.. rubric:: SERVICES

A python dictionary mapping service names to service instances. The same restrictions for device names applies to service
names. Services will also accesible as attributes of the beamline objects.

.. rubric:: CONSOLE

Similar to **DEVICES** except devices specified here will only be available within the beamline console
application.

