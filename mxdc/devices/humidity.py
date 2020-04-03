from zope.interface import implementer

from mxdc import Device
from mxdc.devices.misc import Positioner, SimPositioner
from mxdc.utils.log import get_module_logger
from .interfaces import IHumidifier

logger = get_module_logger(__name__)


@implementer(IHumidifier)
class Humidifier(Device):
    """
    Humidity Controller

    :param root_name: root process variable name of device
    """
    def __init__(self, root_name):
        Device.__init__(self)
        self.name = 'Humidity Controller'
        self.humidity = Positioner('%s:SetpointRH' % root_name, '%s:RH' % root_name)
        self.temperature = Positioner('%s:SetpointSampleTemp' % root_name, '%s:SampleTemp' % root_name)
        self.dew_point = Positioner('%s:SetpointDewPointTemp' % root_name, '%s:DewPointTemp' % root_name)
        self.session = self.add_pv('%s:Session' % root_name)
        self.ROI = self.add_pv('%s:ROI' % root_name)
        self.modbus_state = self.add_pv('%s:ModbusControllerState' % root_name)
        self.drop_size = self.add_pv('%s:DropSize' % root_name)
        self.drop_coords = self.add_pv('%s:DropCoordinates' % root_name)
        self.status = self.add_pv('%s:State' % root_name)

        self.add_components(self.humidity, self.temperature)
        self.modbus_state.connect('changed', self.on_modbus_changed)
        self.status.connect('changed', self.on_status_changed)
        self.set_state(health=(4, 'status','Disconnected'))

    def on_status_changed(self, obj, state):
        if state == 'Initializing':
            self.set_state(health=(1, 'status', state))
        elif state == 'Closing':
            self.set_state(health=(4, 'status','Disconnected'))
            self.set_state(health=(0, 'modbus',''))
        elif state == 'Ready':
            self.set_state(health=(0, 'status',''))

    def on_modbus_changed(self, obj, state):
        if state == 'Disable':
            self.set_state(health=(0, 'modbus',''))
            self.set_state(health=(4, 'modbus','Communication disconnected'))
        elif state == 'Unknown':
            self.set_state(health=(0, 'modbus',''))
            self.set_state(health=(4, 'modbus','Communication state unknown'))
        elif state == 'Enable':
            self.set_state(health=(0, 'modbus',''))


@implementer(IHumidifier)
class SimHumidifier(Device):
    """
    Simulated Humidity Controller
    """

    def __init__(self):
        super(SimHumidifier, self).__init__()
        self.name = 'Sim Humidifier'
        self.humidity = SimPositioner('Humidity', pos=73.4, units='%', delay=True, noise=5)
        self.temperature = SimPositioner('Temperature', pos=293, units='K', noise=2)
        self.dew_point = SimPositioner('Dew Point', pos=287.68, units='K')

        self.drop_size = SimPositioner('Drop Size', pos=150, units='px')
        self.drop_coords = SimPositioner('Drop Coords', pos=((671, 333, 671657),))

        self.add_components(self.humidity, self.temperature, self.dew_point, self.drop_size)

        self.set_state(active=True)
        self.humidity.connect('changed', self._update)
        self.temperature.connect('changed', self._update)

    def _update(self, obj, val):
        temp = self.temperature.get()
        rh = self.humidity.get()
        dp = temp - (100.0 - rh) / 5
        self.dew_point.set(dp)
