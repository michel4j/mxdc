===============
Getting Started
===============

.. contents:: Table of contents
    :depth: 2
    :local:

Starting MxDC
-------------
MxDC can be started either by double-clicking the application icon on the desktop titled "MX Data Collector", or by
typing `mxdc` in a terminal.

If started from the desktop, a new terminal will be opened for printing console log messages.

.. note::

   Closing the terminal will terminate MxDC.

Only one instance of MxDC can be run on a given network at a given moment. This means another user is currently
using MxDC, the program will terminate after presenting a warning.


Stopping MxDC
-------------
MxDC can be stopped either by using the window close button, the Quit menu action in the header bar menu, or the Quit
action of the application menu, if applicable. You should avoid closing MxDC by closing the terminal from which MxDC was
executed, or by using Ctrl-C.


MxLIVE Integration
------------------
MxDC relies on and uses MxLIVE for experiment planning and logging.  Although MxDC can operate without MxLIVE, it
will be significantly limited in usability.

Typically, users plan their experiment by organising their samples into *groups*, and giving each *sample* a unique
name.  For experiments making use of the Automounter, the samples are then organized into *containers*. Before the
experiment, a *shipment* consisting of all the relevant *groups*, *samples*, and relevant *containers* is sent
to the beamline.

When MxDC starts-up, it fetches sample information from MxLIVE. The information fetched, includes details about exact
locations in the Automounter as configured by beamline staff. This information can then be used to mount specific
samples, and also to organize dataset storage in the file system.


Creating Directories
--------------------

By default, a top-level directory is created for each beamtime *session*, within which all data will be stored. It is
no longer possible to store data out-side of this directory using MxDC, and users are strongly advised
not to move data files from their saved locations.

.. note::

   For example:   A session directory might look like:  */users/fodje/CMCFBM-20171018*. Note that the name
   the beamline acronym and the start date of the *session*.

MxDC now automatically organizes how directories are created for saving datasets and related output files within the
*session* directory. A single configuration parameter *Directory Template*, accesible through the Application
Header Bar Menu, allows users to configure a preferred directory template. The parameter only needs to be set once
but there is no limit on how often it can be changed.

.. topic:: Directory Template

    All directories will be created within the top-level session directory
    according to the specified template. You can use variables for substituting context-specific values.

    Available variables: *{sample}, {group}, {container}, {port}, {date}, {activity}*.

    The default template is *"/{group}/{sample}/{activity}/"* which will produce the following directories structure
    for a sample named **bchi-1** in a group named **bchi**:

    .. glossary::
        MAD Scan output files
            /users/fodje/CMCFBM-20171018/bchi/bchi-1/mad-scan/

        Raster Scan files
            /users/fodje/CMCFBM-20171018/bchi/bchi-1/raster/

        Full Datasets
            /users/fodje/CMCFBM-20171018/bchi/bchi-1/data/

        Test Images
            /users/fodje/CMCFBM-20171018/bchi/bchi-1/test/


    Note that additional strings can be used in the template as well, and the sequence of template variables
    is arbitrary. For example, the template *"/CONFIDENTIAL/{activity}/{group}/{sample}/"* will produce a
    directory */users/fodje/CMCFBM-20171018/CONFIDENTIAL/data/bchi/bchi-1/* for the data activity.


