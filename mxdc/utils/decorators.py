import threading
import time
from functools import wraps
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


def memoize(f):
    """ Memoization decorator for functions taking one or more arguments. """

    class Memodict(object):
        def __init__(self, f):
            self.store = {}
            self.f = f

        def __call__(self, *args):
            if args in self.store:
                return self.store[args]
            else:
                ret = self.store[args] = self.f(*args)
                return ret

    return Memodict(f)


def async_call(f):
    """
    Run the specified function asynchronously in a thread. Return values will not be available
    :param f: function or method
    """
    from mxdc.com.ca import threads_init

    def new_f(*args, **kwargs):
        threads_init()  # enable epics environment to be active within thread
        return f(*args, **kwargs)

    @wraps(f)
    def _f(*args, **kwargs):
        worker = threading.Thread(target=new_f, args=args, kwargs=kwargs)
        worker.setDaemon(True)
        worker.setName('Async Call: {}'.format(f.__name__))
        worker.start()

    return _f


def ca_thread_enable(f):
    """
    Make sure an active EPICS CA context is available or join one before running
    :param f: function or method
    """
    from mxdc.com.ca import threads_init

    @wraps(f)
    def _f(*args, **kwargs):
        threads_init()
        return f(*args, **kwargs)

    return _f


def timeit(method):
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()

        print(('%r (%r, %r) %2.2f sec' % (method.__name__, args, kw, te-ts)))
        return result

    return timed