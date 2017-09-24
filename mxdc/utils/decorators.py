import threading

from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


def async_call(f):
    """
    Run the specified function asynchronously in a thread. Return values will not be available
    @param f: function or method
    """
    from mxdc.com.ca import threads_init

    def new_f(*args, **kwargs):
        threads_init()  # enable epics environment to be active within thread
        return f(*args, **kwargs)

    def _f(*args, **kwargs):
        threading.Thread(target=new_f, args=args, kwargs=kwargs).start()

    _f.__name__ = f.__name__
    return _f


def ca_thread_enable(f):
    """
    Make sure an active EPICS CA context is available or join one before running
    @param f: function or method
    """
    from mxdc.com.ca import threads_init

    def _f(*args, **kwargs):
        threads_init()
        return f(*args, **kwargs)

    _f.__name__ = f.__name__
    return _f


def log_call(f):
    """
    Log all calls to the function or method
    @param f: function or method
    """
    def new_f(*args, **kwargs):
        params = ['{}'.format(repr(a)) for a in args[1:]]
        params.extend(['{}={}'.format(p[0], repr(p[1])) for p in kwargs.items()])
        params = ', '.join(params)
        logger.debug('<{}({})>'.format(f.__name__, params))
        return f(*args, **kwargs)

    new_f.__name__ = f.__name__
    return new_f
