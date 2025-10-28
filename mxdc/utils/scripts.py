"""Helper functions that expose the entry-point logic of the scripts in `bin/`.

Each function mirrors the code that normally lives in the script's
`if __name__ == "__main__"` block so the script behavior can be
invoked programmatically (useful for tests, embedding, or tooling).

Functions accept an optional `argv` (sequence of strings) where an
argparse-based script exists, allowing tests to pass arguments.
"""
import sys
from typing import Optional, Sequence

__all__ = [
    "archiver",
    "console",
    "hutch_viewer",
    "image_viewer",
    "mxdc",
    "plot_xdi",
    "sim_console",
    "sim_mxdc",
]


def archiver():
    """Run the ArchiverApp (from bin/archiver)."""
    from mxdc.services.archiver import ArchiverApp

    app = ArchiverApp()
    return app.run()


def console():
    """
    Run the Beamline Console (from bin/blconsole).
    """
    import argparse
    from mxdc import conf

    parser = argparse.ArgumentParser(description="Beamline Console")
    parser.add_argument("-b", type=str, help="Beamline Name")

    args = parser.parse_args(sys.argv)
    conf.initialize(name=args.b)

    from mxdc.consoleapp import ConsoleApp

    app = ConsoleApp()
    return app.run()


def hutch_viewer():
    """
    Run the Hutch Viewer (from bin/hutchviewer).
    """
    import argparse
    import logging
    from mxdc import conf
    from mxdc.utils import log

    parser = argparse.ArgumentParser(description="MxDC Hutch Viewer")
    parser.add_argument("-v", action="store_true", help="Verbose Logging")
    parser.add_argument("-d", action="store_true", help="Prefer Dark Mode if available")
    parser.add_argument("-b", type=str, help="Beamline Name")

    args = parser.parse_args(sys.argv)

    if args.v:
        log.log_to_console(logging.DEBUG)
    else:
        log.log_to_console(logging.INFO)

    conf.initialize(name=args.b)

    from mxdc.hutchapp import HutchApp
    app = HutchApp(dark=args.d)
    return app.run()


def image_viewer():
    """Run the Image viewer (from bin/imgview)."""
    from mxdc.imageapp import ImageApp
    from mxdc.utils import log

    log.log_to_console()
    app = ImageApp()
    return app.run()


def mxdc():
    """
    Run the main Mx Data Collector (from bin/mxdc).
    """
    import argparse
    import logging

    from mxdc import conf
    from mxdc.utils import log

    parser = argparse.ArgumentParser(description="Mx Data Collector")
    parser.add_argument("-v", action="store_true", help="Verbose Logging")
    parser.add_argument("-d", action="store_true", help="Prefer Dark Mode if available")
    parser.add_argument("-b", type=str, help="Beamline Name")

    args = parser.parse_args(sys.argv)
    if args.v:
        log.log_to_console(logging.DEBUG)
    else:
        log.log_to_console(logging.INFO)

    conf.initialize(name=args.b)
    from mxdc.mxdcapp import MxDCApp

    app = MxDCApp(dark=args.d)
    return app.run()


def plot_xdi():
    """
    Plot an XDI file (from bin/plotxdi).
    """
    import argparse

    # matplotlib must be configured before importing pyplot
    from matplotlib import use
    use("Gtk3Agg")

    from matplotlib import rcParams
    from matplotlib import pyplot as plt

    from mxdc.utils import xdi

    rcParams["legend.loc"] = "best"
    rcParams["legend.fontsize"] = 8
    rcParams["figure.facecolor"] = "white"
    rcParams["figure.edgecolor"] = "white"
    rcParams["font.family"] = "Cantarell"
    rcParams["font.size"] = 12

    parser = argparse.ArgumentParser(description="Plot XDI data")
    parser.add_argument("file", help="File to plot")
    parser.add_argument("-x", type=str, help="X-axis column name")
    parser.add_argument("-y", type=str, help="Y-axis column name")

    args = parser.parse_args(sys.argv)
    XDI = xdi.read_xdi(args.file)
    names = XDI.get_names()

    xaxis = args.x or names[0]
    yaxis = args.y or names[-1]

    print(f"Columns: {names}")
    fields = {f.value: f for f in XDI["Column"].values()}
    print(f"Plotting: x={xaxis} vs y={yaxis}")
    plt.plot(XDI.data[xaxis], XDI.data[yaxis])
    x_field = fields[xaxis]
    y_field = fields[yaxis]
    plt.xlabel(f"{x_field.value} ({x_field.units})" if x_field.units else f"{x_field.value}")
    plt.ylabel(f"{y_field.value} ({y_field.units})" if y_field.units else f"{y_field.value}")
    plt.show()


def sim_console():
    """Run the simulated Console (from bin/sim-console)."""
    from mxdc import conf

    conf.initialize("SIM-1")
    from mxdc.consoleapp import ConsoleApp

    app = ConsoleApp()
    return app.run()


def sim_mxdc():
    """
    Run the simulated MxDC (from bin/sim-mxdc).
    """
    import argparse
    import logging

    from mxdc import conf
    from mxdc.utils import log

    parser = argparse.ArgumentParser(description="Mx Data Collector")
    parser.add_argument("-v", action="store_true", help="Verbose Logging")

    args = parser.parse_args(sys.argv)

    if args.v:
        log.log_to_console(logging.DEBUG)
    else:
        log.log_to_console(logging.INFO)

    conf.initialize("SIM-1")
    from mxdc.mxdcapp import MxDCApp

    app = MxDCApp()
    return app.run()
