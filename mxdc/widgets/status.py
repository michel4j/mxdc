
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


@Gtk.Template.from_resource('/org/gtk/mxdc/data/data_control.ui')
class DataControl(Gtk.Box):
    __gtype_name__ = 'DataControl'

    action_btn = Gtk.Template.Child()
    action_icon = Gtk.Template.Child()
    stop_btn = Gtk.Template.Child()
    stop_icon = Gtk.Template.Child()
    progress_bar = Gtk.Template.Child()
    progress_fbk = Gtk.Template.Child()
    eta_fbk = Gtk.Template.Child()

@Gtk.Template.from_resource('/org/gtk/mxdc/data/data_status.ui')
class DataStatus(Gtk.Box):
    __gtype_name__ = 'DataStatus'
    omega_fbk = Gtk.Template.Child()
    max_res_fbk = Gtk.Template.Child()
    two_theta_fbk = Gtk.Template.Child()
    energy_fbk = Gtk.Template.Child()
    attenuation_fbk = Gtk.Template.Child()
    aperture_fbk = Gtk.Template.Child()
    sample_fbk = Gtk.Template.Child()
    directory_fbk = Gtk.Template.Child()
    directory_btn = Gtk.Template.Child()

