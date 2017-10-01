.. _intro:

Introduction
============

MxDC (Macromolecular Crystallography Data Collector) is a modular software package layered above the low-level beamline instrument control system. The first layer, also called the beamline control module (BCM), provides a functional abstraction of all hardware devices usually found at MX beamlines, while the graphical userface  provides an integrated user-friendly interface for interactive data acquisition.

This is the documentation for MxDC and the BCM. It documents the application programming interfaces for developers wishing extend or customize the software. Some information about dependences and installation procedures is also provided. 

This document is targeted at beamline administrators or software developers rather than users of MxDC. If you are a user looking for user documentation, please consult the `MxDC user guide <http://cmcf.lightsource.ca/user-guide/user-manual/data-collection/>`_


Prerequisites
-------------

MxDC and the BCM have been designed and tested to work on Linux systems. Although it would probably work after considerable effort on other Unix-like system or even on Windows, we do not recommend Non-Linux systems.

MxDC and the BCM needs at least **Python 2.4** to run. It does not yet run under Python 3+. It is a pure python package which requires no compilation. Additionally, several python modules are required, without which MxDC and the BCM will not run or function correctly. 

**Required modules:**

- `matplotlib` >= 0.99
- `numpy` >= 1.2
- `scipy` >= 0.6
- `python-ctypes` (for python < 2.5  only)
- `python-simplejson` (for python < 2.5 only)
- `python-imaging` >= 1.1.6
- `python-zope-interface` >= 3.3
- `Twisted` >= 8.2
- `avahi-tools` (provides python avahi module needed by mdns module)
- `dbus-python`, usually installed by default on most recent distributions
- `notify-python`
- Others: (`pygtk` usually included with distribution)

.. note:: If using Twisted >= 9.0, `pyasn1`, and `python-crypto` are also required 

**General tips:**

- To avoid dependency nightmares, always prefer packages already available for
  your distribution. Only build where necessary.
- For installation at the CMCF beamlines, dependencies not available as part of the distribution have been built and are available in `/cmcf_apps/deps`. Select rpm folder matching your architechture (x86 or x86_64) and  install the packages.
- On Scientific Linux/RHEL/CENTOS 5+, most of the packages are available from 
  distribution repositories. Make sure you have EPEL and RPMFusion repositories
  enabled from the start. That way, doing yum install <package-name> should get
  you most of the above packages "for free".
- A few of the packages may need to be built. It is recommended to build rpm's and
  and then install those, so you can easily uninstall them or update them, and it is easy to 
  tell what versions are installed.  Therefore, it is not recommended to do::
	
    python setup.py install

  Instead, do::

    python setup.py bdist_rpm

  which should generate an rpm package within the :file:`dist` subdirectory. You can then install the rpm package normally.

**Other Programs/Libraries:**

- CBFlib: this library must be installed to allow MxDC to recognize CBF diffraction image files. If it is not available, only MarCCD and SMV formatted image files will be supported.
- XREC is used for automated crystal centering and should be available in the execution path.
  Without it, the automatec "crystal" and "loop" centering will fail.
- CHOOCH is required for MAD and SAD scans.
- MxLIVE and Autoprocess servers are automatically discovered at run-time but can be specified in 
  the configuration file manually if not part of the local network. Without these, automated data processing
  and uploading of datasets or processing reports will not work.
  
  
Installation
------------  

#. Uncompress the tarball archive into a target directory
#. Edit :file:`deploy/mxdc.csh` and :file:`deploy/mxdc.csh` to suit the installation
#. Create a configuration file in :file:`etc/xxx.py` to match your beamline hardware. It is better
   to copy an existing one and modify it. 
#. Make sure :file:`mxdc.csh` is sourced on login.


Usage
-----

To run the programs:

- `mxdc` will launch the application.
- `sim-mxdc` will lauch the application with simulated devices.
- `sampleviewer` will launch the hutch sample video screen only.
- `hutchviewer` will launch the hutch control screen only.
- `blconsole` will lauch a beamline python console for interactive scanning and manipulation etc.
    	

