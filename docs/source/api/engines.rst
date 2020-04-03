Engines
=======

An MxDC Engine is an object which manages common operations involving multiple devices. Engines can spawn threads
to run operations asynchronously as needed.

All engines in MxDC are derived from the base class :class:`mxdc.Engine` which provides a default set of methods attributes
and signals for all device types. Specific Engines types can be created by subclassing :class:`mxdc.Engine` and adding
required methods, signals and attributes.

.. autoclass:: mxdc.Engine
    :members:


The following are some examples of engines included by default.

.. autoclass:: mxdc.engines.scanning.BasicScan
    :members: