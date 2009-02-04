from zope.interface import Interface, Attribute
from zope.interface import implements, classProvides
from twisted.plugin import getPlugins, IPlugin

class IScript(Interface):
    pass

class Script(object):
    implements(IPlugin)
    def __init__(self):
        pass

script = Script()

list(getPlugins(IScript))

