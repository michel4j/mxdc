import hashlib
import random
import textwrap
from enum import Enum
from typing import Tuple, Union, Sequence

from gi.repository import Gio
from zope.interface import Interface

from mxdc import Object, Property


def find_item(store: Gio.ListStore, item: Object) -> Tuple[bool, int]:
    """
    Find an item in a list store and return
    :param store: List Store to search in
    :param item:  Item to find
    """
    for i, entry in enumerate(store):
        if item == entry:
            return True, i
    return False, -1


def make_key(text: str) -> str:
    """
    Create an ID hash from a string
    :param text: input string
    :return: str
    """
    key = hashlib.blake2s(text.encode('utf-8'), digest_size=8).hexdigest()
    return "-".join(textwrap.wrap(key, width=4))


class ReportBrowserInterface(Interface):
    ...


class ReportState(Enum):
    PENDING, ACTIVE, SUCCESS, FAILED = range(4)


class Item(Object):
    key = Property(type=str, default='')
    name = Property(type=str, default='')
    dict_keys = ['key', 'name']

    def __init__(self, **kwargs):
        super().__init__()
        self.update(**kwargs)

    def __eq__(self, other):
        if isinstance(other, Item):
            return self.key == other.key
        return False

    def update(self, **kwargs):
        """
        Update attributes of the object based on provided key word arguments
        :param kwargs: key word value pairs

        """
        self.set_properties(**kwargs)

    def to_dict(self):
        """
        Convert to dictionary
        """
        # only Item subclasses are allowed here
        get_keys_from = filter(lambda cls: isinstance(cls, Item), self.__class__.__bases__ + (self.__class__,))

        return {
            key: self.get_property(key)
            for cls in get_keys_from
            for key in cls.dict_keys
        }


class ContainerItem(Item):
    children: Gio.ListStore
    child_type: Item

    def __init__(self, **kwargs):
        self.children = Gio.ListStore(item_type=self.child_type)
        super().__init__(**kwargs)

    def update(self, **kwargs):
        """
        Update attributes of the object based on provided key word arguments
        :param kwargs: key word value pairs

        """
        children = kwargs.pop('children', [])
        self.set_properties(**kwargs)
        for item in children:
            self.add(item)

    def find(self, key: str) -> Union[Item, None]:
        """
        Find and return the child for the given key
        :param key: string key
        """
        for child in self.children:
            if child.key == key:
                return child

    def add(self, item: Item):
        """
        Add a new report or update existing report with the same key
        :param item: report
        """
        existing = self.find(item.key)
        if not existing:
            self.children.append(item)
        else:
            existing.update(**item.to_dict())


class Report(Item):
    kind = Property(type=str, default='...')
    score = Property(type=float, default=0.0)
    file = Property(type=str, default='')
    state = Property(type=object)
    strategy = Property(type=object)

    dict_keys = ['kind', 'score', 'file', 'state', 'strategy']

    def __init__(self, **kwargs):
        if 'state' not in kwargs:
            kwargs['state'] = ReportState.SUCCESS
        if 'strategy' not in kwargs:
            kwargs['strategy'] = {}
        super().__init__(**kwargs)

    def __str__(self):
        return f'{self.kind[:3]} | {self.score:0.2f}'


class Data(ContainerItem):
    kind = Property(type=str, default='...')
    size = Property(type=int, default=0)
    file = Property(type=str, default='')
    selected = Property(type=bool, default=False)

    dict_keys = ['kind', 'size', 'file', 'selected']
    child_type = Report

    def __str__(self):
        return f'{self.kind[:3]} | {self.size} imgs'

    def score(self) -> float:
        """
        Representative score for the dataset is the best report score of all reports
        """
        return max(
            report.score for report in self.children
        )


class SampleItem(ContainerItem):
    group = Property(type=str, default='')
    port = Property(type=str, default='')

    dict_keys = ['group', 'port']
    child_type = Data

    def __str__(self):
        return f'{self.name} - {self.group} | {self.port}'

    def score(self) -> float:
        """
        Representative score for the sample is the best report score of all datasets
        """
        return max(
            data.score() for data in self.children
        )


def get_random_json():
    return random.choice([
        '/data/Xtal/643/A1_2-native/report.json',
        '/data/Xtal/643/proc-2/report.json',
        '/data/Xtal/643/proc-3/report.json',
        '/data/Xtal/BioMAX/insu6_1-native/report.json',
        '/data/Xtal/CLS0026-5-native/report.json',
        '/data/Xtal/Diamond/Mtb_MTR_std_pfGDR_1_1-native/report.json',
        '/data/Xtal/Diamond/Mtb_MTR_std_pfGDR_4_1-native/report.json',
        '/data/Xtal/Diamond/Mtb_MTR_std_pfGDR_4_2-native/report.json',
        '/data/Xtal/IDEiger/lyso1/lysotest1-native/report.json',
        '/data/Xtal/IDEiger/lyso10/lysotest10-native/report.json',
        '/data/Xtal/IDEiger/lyso11/lysotest11-native/report.json',
        '/data/Xtal/IDEiger/lyso15/lysotest15-native/report.json',
        '/data/Xtal/IDEiger/lyso15/lysotest15-native-orig/report.json',
        '/data/Xtal/IDEiger/lyso2/lysotest2-native/report.json',
        '/data/Xtal/IDEiger/lyso3/lysotest3-native/report.json',
        '/data/Xtal/IDEiger/lyso4/lysotest4-native/report.json',
        '/data/Xtal/IDEiger/lyso8/lysotest8-native1/report.json',
        '/data/Xtal/IDEiger/lyso9/lysotest9-native/report.json',
        '/data/Xtal/IDEiger/proc-3/report.json',
        '/data/Xtal/SOLEIL/200Hz/3_5_200Hz_1-native/report.json',
        '/data/Xtal/Tutorial/xtal_1_5-native/report.json',
        '/home/michel/Work/insul/insu6_1-native/report.json']
    )
