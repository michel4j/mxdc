from threading import Lock

from gi.repository import GObject


class StateMachine(GObject.GObject):

    STATES = []  # list of states in sequence, wraps around at the end
    VALUES = []  # list of values required to advance, wraps around at end

    state = GObject.Property(type=object)
    value = GObject.Property(type=object)

    def __init__(self, initial, name='State Machine'):
        super(StateMachine, self).__init__()
        self.name = name
        self.lock = Lock()
        assert len(self.STATES) == len(self.VALUES), 'Inconsitent ({} != {})'.format(len(self.STATES), len(self.VALUES))
        self.change_state(initial)

    def change_state(self, state):
        assert (state in self.STATES), 'Invalid State: {}'.format(state)
        index = self.STATES.index(state)
        with self.lock:
            self.props.condition = self.VALUES[index]
            self.props.state = self.STATES[index]

    def update(self, value):
        if value == self.props.value:
            index = (self.STATES.index(self.props.state) + 1) % len(self.STATES)
            state = self.STATES[index]
            self.change_state(state)