
import os
import hdf5plugin
import numpy

from ctypes import cdll, c_size_t, c_int64, create_string_buffer, byref, c_void_p

# Load BitShuffle library
#  * Worker routines return an int64_t which is the number of bytes processed
#  * if positive or an error code if negative.
#  *
#  * Error codes:
#  *      -1    : Failed to allocate memory.
#  *      -11   : Missing SSE.
#  *      -12   : Missing AVX.
#  *      -80   : Input size not a multiple of 8.
#  *      -81   : block_size not multiple of 8.
#  *      -91   : Decompression error, wrong number of bytes processed.
#  *      -1YYY : Error internal to compression routine with error code -YYY.
#
bshuflib = cdll.LoadLibrary(os.path.join(hdf5plugin.PLUGINS_PATH, "libh5bshuf.so"))


# bshuf_compress_lz4
# -------------------------
# int64_t bshuf_compress_lz4(
#   const void* in,
#   void* out,
#   const size_t size,
#   const size_t elem_size,
#   size_t block_size
# );
#  * Parameters
#  * ----------
#  *  in : input buffer, must be of size * elem_size bytes
#  *  out : output buffer, must be large enough to hold data.
#  *  size : number of elements in input
#  *  elem_size : element size of typed data
#  *  block_size : Process in blocks of this many elements. Pass 0 to
#  *  select automatically (recommended).
#  *
#  * Returns
#  * -------
#  *  number of bytes used in output buffer, negative error-code if failed.
#
bshuf_compress_lz4 = bshuflib.bshuf_compress_lz4
bshuf_compress_lz4.argtypes = [c_void_p, c_void_p, c_size_t, c_size_t, c_size_t]
bshuf_compress_lz4.restype = c_int64


def compress_lz4(arr: numpy.ndarray):
    """
    Compress Numpy array using bitshuffle and lz4 and return bytes

    :param arr: Numpy.ndarray
    :return: string of bytes
    """

    output = create_string_buffer(arr.size * arr.dtype.itemsize)
    res = bshuf_compress_lz4(
        c_void_p(arr.ctypes.data),
        byref(output),
        c_size_t(arr.size),
        c_size_t(arr.dtype.itemsize),
        c_size_t(0)
    )
    if res > 0:
        return output[:res]
    elif res == -1:
        raise MemoryError('Failed to allocate memory.')
    elif res == -11:
        raise RuntimeError('Missing SSE')
    elif res == -12:
        raise RuntimeError('Missing AVX')
    elif res == -80:
        raise ValueError('Input size not a multiple of 8')
    elif res == -81:
        raise ValueError('Block size not a multiple of 8')
    else:
        raise RuntimeError(f'Internal error. Code: {res}')


# bshuf_decompress_lz4
# --------------------
# int64_t bshuf_decompress_lz4(
#     const void* in,
#     void* out,
#     const size_t size,
#     const size_t elem_size,
#     size_t block_size
# );
# * Parameters
#  * ----------
#  *  in : input buffer
#  *  out : output buffer, must be of size * elem_size bytes
#  *  size : number of elements in input
#  *  elem_size : element size of typed data
#  *  block_size : Process in blocks of this many elements. Pass 0 to
#  *  select automatically (recommended).
#  *
#  * Returns
#  * -------
#  *  number of bytes consumed in *input* buffer, negative error-code if failed.
bshuf_decompress_lz4 = bshuflib.bshuf_decompress_lz4
bshuf_decompress_lz4.argtypes = [c_void_p, c_void_p, c_size_t, c_size_t, c_size_t]
bshuf_decompress_lz4.restype = c_int64


def decompress_lz4(data: bytes, shape: tuple, dtype: numpy.dtype, block_size=0):
    """
    Decompress and unshuffle bytestring using bitshuffle and lz4 and return
    a numpy ndarray

    :param data: bytes
    :param shape: tuple representing the data shape of the original array
    :param dtype: numpy.dtype of original array used for compression
    :param block_size: block_size. Defaults to 0 for automatic determination.
    :return: numpy.ndarray
    """

    output = numpy.empty(shape=shape, dtype=dtype)
    input = numpy.frombuffer(data, dtype=numpy.uint8)

    res = bshuf_decompress_lz4(
        input.ctypes.data_as(c_void_p),
        output.ctypes.data_as(c_void_p),
        output.size,
        dtype.itemsize,
        block_size
    )
    if res > 0:
        return output
    elif res == -1:
        raise MemoryError('Failed to allocate memory.')
    elif res == -11:
        raise RuntimeError('Missing SSE')
    elif res == -12:
        raise RuntimeError('Missing AVX')
    elif res == -80:
        raise ValueError('Input size not a multiple of 8')
    elif res == -81:
        raise ValueError('Block size not a multiple of 8')
    elif res == -91:
        raise ValueError('Decompression error, wrong number of bytes processed.')
    else:
        raise RuntimeError(f'Internal error. Code: {res}')

