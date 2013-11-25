from zope.interface.adapter import AdapterRegistry
from zope.interface import providedBy
from zope.interface.interface import adapter_hooks

registry = AdapterRegistry()

def _hook(provided, obj):
    if provided.__name__ in ['IPathImportMapper', 'IPlugin']:
        return None
    adapter = registry.lookup1(providedBy(obj), provided, '')
    if adapter is not None:
        return adapter(obj)
    else:
        return None

adapter_hooks.append(_hook)

def _del_hook():
    adapter_hooks.remove(_hook)

import atexit
atexit.register(_del_hook)
