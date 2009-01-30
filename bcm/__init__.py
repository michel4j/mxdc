from zope.interface.adapter import AdapterRegistry
from zope.interface import providedBy
from zope.interface.interface import adapter_hooks

registry = AdapterRegistry()

def _hook(provided, object):
    adapter = registry.lookup1(providedBy(object),
                               provided, '')
    return adapter(object)

adapter_hooks.append(_hook)
