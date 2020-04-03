Objects
=======

The fundamental base class for the key components of MxDC is the :class:`Object`.  It is a subclass of
`GObject.Object <https://pygobject.readthedocs.io/en/latest/guide/api/gobject.html>`__
and provides several key features such as Signals registration and connection to callbacks, typed properties, and
all other features supported by `GObject.Object`.

Signals are a system for creating named events and registering callbacks to them. :class:`mxdc.Signal` is an alias for
:class:`GObject.Signal`

.. rubric:: Example

The following is an example of an object supporting two signals with different
numbers of arguments, how to connect to callbacks and trigger events.

.. note::

    An appropriate main-loop is required. These examples can be tried out using an ipython shell with the
    `Gtk3` main loop active.  This can be activated using the IPython magic command ``%gui gtk3``.


.. code-block:: python

    from mxdc import Object, Signal

    class Door(Object):

        class Signals:
            opened = Signal('opened', arg_types=(bool,))
            locked = Signal('locked', arg_types=(bool, str))


    def on_lock(obj, state, message):
        print('Door {}locked, {}.'.format('un' if not state else '', message))

    def on_opened(obj, state):
        print('Door {}.'.format('opened' if state else 'closed'))


.. code-block:: pycon

    >>> door = Door()
    >>> door.connect('opened', on_opened)
    17L
    >>> door.connect('locked', on_lock)
    18L
    >>> door.emit('opened', True)
    Door opened.

    >>> door.emit('opened', False)
    Door closed.

    >>> door.emit('locked', True, 'come back later')
    Door locked, come back later.

    >>> # set state and emit multiple signals simultaneously
    >>> door.set_state(locked=(True, 'access forbidden'), opened=False)
    Door locked, access forbidden.
    Door closed.

    >>> door.get_state('locked')
    (True, "access forbidden")

.. rubric:: API Details

.. autoclass:: mxdc.Object
    :members:

