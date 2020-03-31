==================
For Beamline Staff
==================

.. contents:: Table of contents
    :depth: 1
    :local:


MxDC includes several tools to make the lives of beamline staff easier.  These include a HutchViewer, a beamline console
for troubleshooting and commissioning, archival scripts for backing up user data to portable drives, and a simulated
beamline for training purposes.


Hutch Viewer
------------
The Hutch Viewer is a simplified version of the MxDC interface that is suitable for display in an experimental hutch.
It provides only the features available on the setup page of MxDC together with a few additional features such as a
sample video viewer, and a diffraction image viewer.


Beamline Console
----------------
The beamline console is a command line enhanced IPython shell allowing users to configure and control beamline
devices outside of the MxDC GUI.  Commissioning activities such as scanning, plotting, fitting and scripting are all
supported. As a normal python prompt, it allows traditional python scripts to be used in combination with device
control and data-acquisition features provided by MxDC. In addition, the introspection capabilities of IPython can be
used to investigate objects.

The beamline console includes a plot window which displays live data from currently executing scans, and results of
some analysis after scans, such as curve-fitting.

The beamline console can be started using the `blconsole` command.

.. code-block:: bash

   $ blconsole


.. figure:: console.png
    :align: center
    :width: 100%
    :alt: Beamline Console

    Screenshot of the Beamline Console showing the plot window and command prompt.

Default Environment
~~~~~~~~~~~~~~~~~~~
The following objects and classes are available in the default environment once the beamline console is launched.

    * `bl` -  A reference to the beamline object. The devices registered will be available as attributes of this object.
    * `plot` - A reference to the plot controller.
    * `fit` - A fitting Manager object. This can be used to do curve fitting on the most recent scan data.
    * Various Scan types - :class:`AbsScan`, :class:`AbsScan2`, :class:`RelScan`, :class:`RelScan2`, :class:`GridScan`, :class:`SlewScan`, :class:`SlewGridScan` etc.



.. warning:: Avoid shadowing these names by assigning to them.


Performing Scans
~~~~~~~~~~~~~~~~
To perform a scan, create a scan instance with the appropriate parameters and then call the start method to run the
scan asynchronously.  The plot window should update in realtime as the scan progresses.

.. code-block:: python

    >>> scan = RelScan(bl.dcm_pitch, -0.1, 0.1, 20, 0.1, bl.i1)
    >>> scan.start()


While the scan is running, it can be stopped before it is complete

.. code-block:: python

    >>> scan.stop()

Sometimes, it is desirable to extend the scan range once the scan is complete, without destroying the previously
acquired data.  In such cases, use the `scan.extend(...)` method as follows.  The method takes a single parameter
which is the amount to extend the scan by in steps except for a `SlewScan` where the amount is the actual additional
travel range for the motor.

.. code-block:: python

    >>> scan.extend(10)   # 10 more steps for all other scan types
    >>> scan.extend(2.5)  # 2.5 mm more for a Slew Scan

For help on required parameters for a specific type of can, you can use the IPython help shortcut

.. code-block::

    >>> SlewScan?
    Init signature: SlewScan(m1, p1, p2, *counters, i0=None, speed=None)

    Docstring:
    A Continuous scan of a single motor.
    :param m1: motor or positioner
    :param p1: start position
    :param p2: end position
    :param counters: one or more counters
    :param i0: reference counter
    :param speed:  scan speed of m1


Fitting
~~~~~~~
To perform curve-fitting on the results of a scan, you can use the fit object as follows. Once the fit is complete, a
fitted curve will be overlaid on the plot window and the fitted parameters will be returned. You can specify the data
column to be used for fitting. The first  column is selecte by default if none is specified.

.. code-block:: python

    >>> fit.gaussian('i1')
    {'ymax': 38.753925,
     'midp': -0.010566544083663901,
     'fwhm': 0.07076730539816214,
     'cema': -0.0009469308321938418,
     'midp_hist': -0.01071071087031274,
     'fwhm_hist': 0.08288288411793407,
     'ymax_hist': 38.75275534939397}


The following types of functions are available for fitting: `gaussian`, `lorentz`, `voigt`.


Saved Scan Data
~~~~~~~~~~~~~~~
Scan results are saved as GZip compressed XDI files like `~/Scans/YYYY/mmm/xxxxxx-HHMMSS.xdi.gz`. These files can
be displayed later using the `plotxdi` command provided with MxDC.


.. code-block::

    usage: plotxdi [-h] [-x X] [-y Y] file

    Plot XDI data

    positional arguments:
      file        File to plot

    optional arguments:
      -h, --help  show this help message and exit
      -x X        X-axis column name
      -y Y        Y-axis column name


