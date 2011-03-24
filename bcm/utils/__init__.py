try:
    import json
except (ImportError, NameError):
    try:
        from django.utils import simplejson as json
    except (ImportError, NameError):
        import simplejson as json
