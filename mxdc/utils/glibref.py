import ctypes
import gi
from ctypes import pythonapi


class _PyGObject_Functions(ctypes.Structure):
    _fields_ = [
        ('pygobject_register_class',
         ctypes.PYFUNCTYPE(ctypes.c_void_p)),
        ('pygobject_register_wrapper',
         ctypes.PYFUNCTYPE(ctypes.c_void_p)),
        ('pygobject_lookup_class',
         ctypes.PYFUNCTYPE(ctypes.c_void_p)),
        ('pygobject_new',
         ctypes.PYFUNCTYPE(ctypes.py_object, ctypes.c_void_p)),
    ]


class PyGObjectCAPI(object):
    def __init__(self):
        addr = self._as_void_ptr(gi._gobject._PyGObject_API)
        self._api = _PyGObject_Functions.from_address(addr)

    @classmethod
    def _capsule_name(cls, capsule):
        pythonapi.PyCapsule_GetName.restype = ctypes.c_char_p
        pythonapi.PyCapsule_GetName.argtypes = [ctypes.py_object]
        return pythonapi.PyCapsule_GetName(capsule)

    @classmethod
    def _as_void_ptr(cls, capsule):
        name = cls._capsule_name(capsule)
        pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
        pythonapi.PyCapsule_GetPointer.argtypes = [
            ctypes.py_object, ctypes.c_char_p]
        return pythonapi.PyCapsule_GetPointer(capsule, name)

    def to_object(self, addr):
        return self._api.pygobject_new(addr)


capi = PyGObjectCAPI()
