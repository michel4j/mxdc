Getting Started
===============

Starting MxDC
-------------
Based on how MxDC is installed in your environment, it can be started either by double-clicking the application icon
or by typing `mxdc` in a terminal.

Only one instance of MxDC can be run on a given subnet at a given moment. If another user is currently
using MxDC, the program will terminate after presenting a warning.


Stopping MxDC
-------------
MxDC can be stopped either by using the window close button, the Quit menu action in the header bar menu, or the Quit
action of the application menu, if applicable. You should avoid closing MxDC by closing the terminal from which MxDC was
executed, or by using Ctrl-C.


MxLIVE Integration
------------------
The MxDC Application relies on and uses MxLIVE for experiment planning and logging.  Although MxDC can operate without MxLIVE, it
will be significantly limited in usability.

Typically, users plan their experiment by organising their samples into *groups*, and giving each *sample* a unique
name.  For experiments making use of the Automounter, the samples are then organized into *containers*. Before the
experiment, a *shipment* consisting of all the relevant *groups*, *samples*, and relevant *containers* is sent
to the beamline.

When MxDC starts-up, it fetches sample information from MxLIVE. The information fetched, includes details about exact
locations in the Automounter as configured by beamline staff. This information can then be used to mount specific
samples, and also to organize data storage in the file system.


Creating Directories
--------------------

By default, a top-level directory is created for each beamtime *session*, within which all data will be stored. It is
no longer possible to store data out-side of this directory using MxDC, and users are strongly advised
not to move data files from their saved locations.

.. note::

    For example:   A session directory might look like */users/fodje/CMCFBM-20171018* which includes the beamline
    acronym and the start date of the *session*.

MxDC automatically organizes how directories are created for saving datasets and related output files within the
*session* directory. A single configuration parameter *Directory Template*, accesible through the Application
Menu, allows users to configure a preferred directory template. The parameter only needs to be set once
but there is no limit on how often it can be changed.

.. rubric:: Directory Template

All directories will be created within the top-level session directory
according to the specified template. You can use sample variables for substituting context-specific values.

Available variables: *{sample}, {group}, {container}, {position}, {port}, {date}, {activity}*.

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


