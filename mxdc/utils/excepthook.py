import getpass
import smtplib
import socket
import sys
import threading
import traceback
from email.mime.text import MIMEText
from gi.repository import Gtk
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs

logger = get_module_logger(__name__)


class ExceptHook(object):
    def __init__(self, name='MxDC', exit_function=sys.exit, emails=None, prefix='Bug Report', ignore=[]):
        self.exit_function = exit_function
        self.system_hook = sys.excepthook
        self.emails = emails
        self.prefix = '{} {}'.format(name, prefix)
        self.ignore = ignore
        self.name = name
        self.lock = threading.Lock()

    def send_mail(self, subject, message):
        from_addr = '{}@{}'.format(getpass.getuser(), socket.gethostname())
        to_addr = self.emails
        msg = MIMEText(message)
        msg['Subject'] = '[{}] - {}'.format(self.prefix, subject)
        msg['From'] = from_addr
        msg['To'] = ', '.join(to_addr)

        try:
            server = smtplib.SMTP('localhost')
            server.sendmail(from_addr, to_addr, msg.as_string())
            server.quit()
        except socket.error:
            logger.error('Could not submit bug report.')
        else:
            logger.info('Bug report submitted.')

    def install(self):
        sys.excepthook = self.handle_exception

    def uninstall(self):
        sys.excepthook = self.system_hook

    def handle_exception(self, exctyp, value, tb):
        if self.lock.locked():
            self.uninstall()  # exceptions piled-up
        else:
            with self.lock:
                if tb is None:
                    trace_list = traceback.extract_stack()[:-1]
                    trace_info = traceback.format_list(trace_list)
                else:
                    trace_info = traceback.format_exception(exctyp, value, tb)

                header = '\n'.join([exctyp.__name__, '-' * len(exctyp.__name__)])
                trace = "".join([header, '\n'] + trace_info)

                if exctyp in self.ignore:
                    logger.error(trace)
                    return

                title = "{} has stopped".format(self.name)
                message = (
                    "An unexpected problem has been detected. The developers will be notified. "
                    "You can either ignore the problem and attempt to continue or quit the program."
                )
                buttons = (
                    ('Ignore', Gtk.ResponseType.CANCEL),
                    ('Quit', Gtk.ResponseType.CLOSE)
                )

                dialog = dialogs.exception_dialog(title, message, details=trace, buttons=buttons)
                response = dialog.run()
                dialog.destroy()
                if response == Gtk.ResponseType.CANCEL:
                    logger.warning("{} will attempt to continue.".format(self.name))
                    self.send_mail(exctyp.__name__, trace)
                elif response == Gtk.ResponseType.CLOSE:
                    self.send_mail(exctyp.__name__, trace)
                    self.exit_function()
