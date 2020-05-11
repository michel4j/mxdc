Setup
=====

The Setup View allows users to view, adjust and diagnose general beamline parameters outside of the context of an experiment.

.. figure:: images/setup.svg
    :align: center
    :width: 100%
    :alt: MxDC Setup View

    Screenshot of the Setup View

Device Parameters
-----------------
The device parameters are shown on the top-right hand corner of the Setup View. The exact parameters available may
vary with beamline but usually include, *energy*, beam *attenuation*, *beam aperture*, *detector distance*, *beam stop
distance* and *goniometer Omega* angle.  Where applicable, the current value is displayed on the left and a new value
can be entered on the right.  A button allows the parameter to be applied. This operation may cause the device to move
if it is a motor and feedback will be provided while it moves. The motion can also be stopped using the button.


.. image:: images/parameters.png
    :align: center
    :alt: MxDC Setup View


The image above shows a screenshot of the Device Parameters. The detector distance is currently moving to the requested
position of 100 mm, therefore the current position is shown as red, and the button icon is a red animated square.
Clicking on the button will issue a stop command for the detector.  The beam aperture parameter is
a drop-down menu showing the possible values. The detector two-theta angle is in an error state.


Hutch Video
-----------
The Hutch Video Feed is a Pan-Tilt-Zoom Camera inside the experimental enclosure (hutch). This alows the user
to inspect the hutch remotely.

.. image:: images/hutch-video.png
    :align: center
    :alt: Hutch Video

The camera can be controlled by clicking on the image to re-center the view, or by selecting pre-defined positions
from the drop-down menu where available.

Beamline Status
---------------
The beamline status shows the status of various essential components on the beamline and allows users to quickly
diagnose problems on the beamline.

.. image:: images/diagnostics.png
    :align: center
    :alt: Beamline Status

Each entry on the list consists of an icon which conveys the state
(*Good, Bad, Warning, unknown*), a description of the component, and descriptive text about the current state.  The color
of the icon changes from blue to green to orange to red as the component changes from *unknown* to *good* to
*warning* to *error*.  In most cases, data acquisition can only proceed reliably if all components are *good*. In
some cases, it may be acceptable to proceed with some components in the *warning* state. Always cross-check with
beamline staff if in doubt.
