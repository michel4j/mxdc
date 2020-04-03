Devices
=======

An MxDC Device is a high-level abstraction of a beamline hardware device that allows MxDC to interact with the hardware.
From our perspective, the only relevant details are those important for the function that is common
across all devices of the same type.

Devices of the same type are expected to provide a minimum common subset of functions and *behaviours* that determine the
interface of the device.  The interface for the device type is therefore a common set of attributes, methods, signals
and *behaviours*.

All devices in MxDC are derived from the base class :class:`mxdc.Device` which provides a default set of methods attributes
and signals for all device types. Specific device types can be created by subclassing :class:`mxdc.Device` and adding
required methods, signals and attributes.

.. autoclass:: mxdc.Device
    :members:


The following are some examples of device types included by default. To implement variants of the these built-in device
types, simply subclass them and provide implementation details of the interface.

Auto Mounters
-------------
Auto mounters provide abstractions for robotic sample mounting systems for loading samples onto beamlines.

.. py:currentmodule:: mxdc.devices.automounter
.. autoclass:: AutoMounter
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    sam.UncleSAM
    sam.SAM
    isara.AuntISARA
    isara.ISARA
    cats.CATS
    sim.SimSAM


Beam Tuners
-----------
.. py:currentmodule:: mxdc.devices.boss
.. autoclass:: BaseTuner
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    BOSSTuner
    MOSTABTuner
    SIMTuner

Counters
--------
Counters are simple devices that are continuously monitoring hardware feedback, like temperature, current, voltage,
vacuum pressure, etc. Counters provide mechanisms for averaging or integrating those values over peiods of time.

.. py:currentmodule:: mxdc.devices.counter

.. autoclass:: BaseCounter
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimCounter
    Counter

Detectors
---------
In the context of MxDC, detectors are 2D imaging detector/cameras the acquire series of images.

.. py:currentmodule:: mxdc.devices.detector

.. autoclass:: BaseDetector
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimDetector
    RayonixDetector
    ADSCDetector
    PilatusDetector
    EigerDetector

Goniometers
-----------
Goniometers are rotary devices that can be configured to perform scans combined with triggering of detectors for
acquiring data.

.. py:currentmodule:: mxdc.devices.goniometer

.. autoclass:: BaseGoniometer
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimGonio
    ParkerGonio
    MD2Gonio
    GalilGonio
    OldMD2Gonio

Motors
------
.. py:currentmodule:: mxdc.devices.motor

.. autoclass:: BaseMotor
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimMotor
    Motor
    VMEMotor
    CLSMotor
    APSMotor
    PseudoMotor
    BraggEnergyMotor
    ResolutionMotor

Multi-Channel Analyzers
-----------------------
Abstractions for configuring and acquiring data from a multichannel analyzers

.. py:currentmodule:: mxdc.devices.mca

.. autoclass:: BaseMCA
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimMCA
    XFlashMCA
    VortexMCA


Mode Managers
-------------
Mode managers are devices which manage the beamline sample environment. A "mode" is a specific configuration
of the sample environment suitable for a specific type of activity. Examples of modes include:

* `mount`:  Sample environment suitable for mounting/loading samples
* `center`: Sample centering mode
* `collect`: Data acquisition mode
* `align`: Beam alignment mode

.. py:currentmodule:: mxdc.devices.manager

.. autoclass:: BaseManager
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimModeManager
    MD2Manager
    ModeManager


Shutters
--------
.. py:currentmodule:: mxdc.devices.shutter

.. autoclass:: BaseShutter
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimShutter
    EPICSShutter
    StateLessShutter
    ToggleShutter
    ShutterGroup
    Shutter

Stages
------
.. py:currentmodule:: mxdc.devices.stages

.. autoclass:: BaseSampleStage
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SampleStage


Storage Ring
------------
.. py:currentmodule:: mxdc.devices.synchrotron

.. autoclass:: BaseStorageRing
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    StorageRing


Video
-----
.. py:currentmodule:: mxdc.devices.video

.. autoclass:: VideoSrc
    :members:

.. rubric:: Sub-classes

.. autosummary::
    :toctree: generated
    :nosignatures:

    SimCamera
    SimPTZCamera
    MJPGCamera
    JPGCamera
    REDISCamera
    AxisCamera
    AxisPTZCamera
