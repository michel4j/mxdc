============
Installation
============

Step by Step
------------
#. Install dependencies

	- ``matplotlib`` >= 0.99
	- ``numpy`` >= 1.2
	- ``scipy`` >= 0.6
	- ``python-ctypes`` (for python < 2.5  only)
	- ``python-simplejson`` (for python < 2.5 only)
	- ``python-imaging`` >= 1.1.6
	- ``python-zope-interface`` >= 3.3
	- ``Twisted`` >= 8.2
	  NOTE: if using Twisted 9.0, ``pyasn1``, and ``python-crypto`` are also required 
	- ``avahi-tools`` (provides python avahi module needed by mdns module)
	- ``dbus-python``, usually installed by default on most recent distributions
	- Others: (``pygtk`` usually included with distribution)
    
#. Uncompress archive into target directory
#. Edit ``deploy/bcm.csh`` so suit the installation
#. Create a configuration file in etc/xxx.conf to match your beamline. It is better
   to copy an existing one and modify it. 
#. Make sure bcm.csh is sourced on login.
#. To run:
    - ``mxdc`` will launch the application
    - ``sim-mxdc`` will lauch the application with simulated devices
    - ``sampleviewer`` will launch the hutch sample video screen only
    - ``hutchviewer`` will launch the hutch control screen only
    - ``blconsole`` will lauch a beamline python console for interactive scanning and manipulation etc.
    	
General Tips
------------
- To avoid dependency nightmares, always prefer packages already available for
  your distribution. Only build where necessary.
- For installation at CMCF, prebuilt dependencies are available
  in ``/cmcf_apps/deps``. Select rpm folder matching your installation and
  install the packages.
- On Scientific Linux/RHEL/CENTOS 5+, most of the packages are available from 
  distribution repositories. Make sure you have EPEL and RPMFusion repositories
  enabled from the start. That way, doing yum install <package-name> should get
  you most of the above packages "for free".
- A few of the packages may need to be built. It is recommended to build rpm's and
  and then install those, so you can easily uninstall them or update them, and it is easy to 
  tell what versions are installed.  Therefore, it is not recommended to do:
	
  ``python setup.py install``

  Instead, do:

  ``python setup.py bdist_rpm``

  and then ``rpm -Uvh`` the resulting rpm package in ``dist/<...>.rpm``.