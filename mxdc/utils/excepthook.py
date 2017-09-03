##    excepthook.py
##
## Copyright (C) 2013 Michel Fodje <michel.fodje@lightsouce.ca>
## Copyright (C) 2006 Paul Walker <paul@blacksun.org.uk>
## Copyright (C) 2005-2006 Yann Le Boulanger <asterix@lagaule.org>
## Copyright (C) 2005-2006 Nikos Kouremenos <kourem@gmail.com>
##
## Initially written and submitted by Gustavo J. A. M. Carneiro
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published
## by the Free Software Foundation; version 2 only.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##

from mxdc.widgets import dialogs
from mxdc.utils.log import get_module_logger
from twisted.internet import reactor
from email.mime.text import MIMEText
import smtplib
from gi.repository import Gtk
import sys
import threading
import traceback
import getpass
import socket

_logger = get_module_logger(__name__)
_exception_in_progress = threading.Lock()

QUIT_FUNCTION = sys.exit


def _send_email(address, subject, message):
    from_addr = '{}@{}'.format(getpass.getuser(), socket.gethostname())
    to_addr = [address, ]
    msg = MIMEText(message)
    msg['Subject'] = 'MxDC Bug Report ({}) - {}'.format(getpass.getuser(), subject)
    msg['From'] = from_addr
    msg['To'] = ', '.join(to_addr)

    try:
        server = smtplib.SMTP('localhost')
        server.sendmail(from_addr, to_addr, msg.as_string())
        server.quit()
    except:
        return False
    return True


def _custom_excepthook(exctyp, value, tb):
    if not _exception_in_progress.acquire(False):
        # Exceptions have piled up, so we use the default exception
        # handler for such exceptions
        _excepthook_save(exctyp, value, tb)
        return

    if tb is None:
        trace_list = traceback.extract_stack()[:-1]
        trace_info = traceback.format_list(trace_list)
    else:
        trace_info = traceback.format_exception(exctyp, value, tb)
    trace = "".join(trace_info)
    primary = "MxDC has stopped working"
    secondary = (
        "An unexpected problem has been detected. You can ignore the "
        "problem and attempt to continue or quit the program."
    )

    buttons = (("Report...", Gtk.ResponseType.HELP),
               ('Ignore', Gtk.ResponseType.CANCEL),
               (Gtk.STOCK_QUIT, Gtk.ResponseType.CLOSE))

    dialog = dialogs.AlertDialog(dialogs.MAIN_WINDOW, Gtk.DialogFlags.MODAL, dialog_type=Gtk.MessageType.ERROR)
    for text, response in buttons:
        btn = dialog.add_button(text, response)
        if response == Gtk.ResponseType.HELP:
            dialog.set_default(btn)
            dialog.set_default_response(Gtk.ResponseType.HELP)

    dialog.set_primary(primary)
    dialog.set_secondary(secondary)
    dialog.set_details(trace)

    def _dlg_cb(dlg, response):
        if response == Gtk.ResponseType.HELP:
            _out = _send_email('cmcf-support@lightsource.ca', exctyp, trace)
            if _out:
                _logger.warning("Bug report has been sent to developers.")
            else:
                _logger.error("Bug report could not be submitted.")
        elif response == Gtk.ResponseType.CLOSE:
            _exception_in_progress.release()
            QUIT_FUNCTION()
        else:
            dlg.destroy()
            _exception_in_progress.release()

    dialog.connect('response', _dlg_cb)
    dialog.show()


_excepthook_save = sys.excepthook


def install(quit_func=None):
    global QUIT_FUNCTION
    sys.excepthook = _custom_excepthook
    if quit_func:
        QUIT_FUNCTION = quit_func


def uninstall():
    global QUIT_FUNCTION
    sys.excepthook = _excepthook_save
    QUIT_FUNCTION = sys.exit

