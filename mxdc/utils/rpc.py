import repr as reprlib
import log

logger = log.get_module_logger(__name__)


def expose(f):
    """
    Add 'exposed_' to methods ._alias field and return it.
    Note: This decorator must be used inside an @expose_service -decorated class.
    For example, if you want to make the method shout() be also callable as
    exposed_shout() expose like this:

        @expose
        def shout(message):
            # ....
    """
    def new_f(*args, **kwargs):
        params = ['{}'.format(reprlib.repr(a)) for a in args[1:]]
        params.extend(['{}={}'.format(p[0], reprlib.repr(p[1])) for p in kwargs.items()])
        params = ', '.join(params)
        logger.debug('{}: <{}({})>'.format(args[0], f.__name__, params))
        return f(*args, **kwargs)

    new_f.__name__ = f.__name__
    new_f._alias = 'exposed_{}'.format(f.__name__)
    return new_f


def expose_service(aliased_class):
    """
    Decorator function that *must* be used in combination with @expose
    decorator. This class will make the magic happen!
    @aliased classes will have their exposed method (via @expose) actually
    exposed.
    This method simply interates over the member attributes of 'aliased_class'
    seeking for those which have an '_alias' attribute and then defines new
    members in the class using those aliases as mere pointer functions to the
    original ones.

    Usage:
        @expose_service
        class MyClass(object):
            @expose
            def boring_method():
                # ...

        i = MyClass()
        i.exposed_coolMethod() # equivalent to i.boring_method()
    """
    original_methods = aliased_class.__dict__.copy()
    for name, method in original_methods.items():
        if hasattr(method, '_alias'):
            setattr(aliased_class, method._alias, method)
    return aliased_class
