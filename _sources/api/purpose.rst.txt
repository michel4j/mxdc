Purpose
=======

**MxDC** is Python framework for creating event-driven beamline data acquisition software systems.  It is based
on `PyGObject <https://pygobject.readthedocs.io/en/latest/index.html>`__ which provides Python bindings for `GObject
<https://developer.gnome.org/gobject/stable/>`__ based libraries like `GTK <https://www.gtk.org/>`__,
`GLib <https://developer.gnome.org/glib/stable/>`__, `GIO <https://developer.gnome.org/gio/stable/>`__ and many more. It
also integrates nicely with the `Twisted <https://twistedmatrix.com/trac/>`__ event-driven networking framework.

If you want to create a command-line or graphical application for abstracting beamline control systems like `EPICS <https://epics.anl.gov>`__
into  higher level experiment control systems, able to perform complex experiments with visualization capabilities, then
the MxDC framework may be the solution. GUI applications written with MxDC integrate nicely with other `GTK <https://www.gtk.org/>`__
based applications  and the `GNOME Desktop <https://www.gnome.org/>`__ environment which is standard on many
Linux operating systems.