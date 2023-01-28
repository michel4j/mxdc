import hashlib
from enum import Enum
from mxdc import Object, Property
from mxdc.utils import glibref


class AnalysisState(Enum):
    PENDING, ACTIVE, SUCCESS, FAILED = range(4)


class Report(Object):
    name = Property(type=str, default='...')
    kind = Property(type=str, default='...')
    score = Property(type=float, default=0.0)
    file = Property(type=str, default='')
    progress = Property(type=float, minimum=0.0, maximum=100.0, default=0.0)
    state = Property(type=object)
    strategy = Property(type=object)

    def __init__(self, **kwargs):
        super().__init__()
        self.props.strategy = {}
        self.props.state = AnalysisState.PENDING
        self.set_properties(**kwargs)

    def update(self, **kwargs):
        self.set_properties(**kwargs)

    def __str__(self):
        return f'{self.kind[:3]} | {self.score:0.2f}'


class Data(Object):
    name = Property(type=str, default='...')
    uuid = Property(type=str, default='...')
    key = Property(type=int, default=0)
    kind = Property(type=str, default='...')
    size = Property(type=int, default=0)
    file = Property(type=str, default='')
    selected = Property(type=bool, default=False)
    reports = Property(type=object)

    def __init__(self, **kwargs):
        super().__init__()
        self.props.reports = {}
        self.set_properties(**kwargs)
        self.props.uuid = hashlib.blake2s(
            self.file.encode('utf-8') + self.name.encode('utf-8'), digest_size=16
        ).hexdigest()

    def update(self, **kwargs):
        self.set_properties(**kwargs)

    def add_report(self, item: Report):
        self.props.reports[item.file] = item
        self.notify('reports')

    def score(self):
        return max(
            report.score for report in self.reports.values()
        )

    def __str__(self):
        return f'{self.kind[:3]} | {self.size} imgs'


class SampleItem(Object):
    name = Property(type=str, default='No Sample')
    group = Property(type=str, default='')
    port = Property(type=str, default='')
    key = Property(type=int, default=0)
    datasets = Property(type=object)

    def __init__(self, **kwargs):
        super().__init__()
        self.props.datasets = {}
        self.set_properties(**kwargs)

    def update(self, **kwargs):
        self.set_properties(**kwargs)

    def add_data(self, item: Data):

        if not item.uuid in self.datasets:
            self.props.datasets[item.uuid] = item
            self.notify('datasets')

        print(self.datasets)


    def score(self):
        return max(
            data.score() for data in self.datasets.values()
        )

    @staticmethod
    def sorter(a_pointer, b_pointer):
        # if objects correctly translated do not translate again
        if isinstance(a_pointer, SampleItem):
            obj_a, obj_b = a_pointer, b_pointer
        else:
            obj_a, obj_b = glibref.capi.to_object(a_pointer), glibref.capi.to_object(b_pointer)
        a, b = obj_a.score(), obj_b.score()

        if a > b:
            return -1
        elif a < b:
            return 1
        else:
            return 0

    def __str__(self):
        return f'{self.name} - {self.group} | {self.port}'






