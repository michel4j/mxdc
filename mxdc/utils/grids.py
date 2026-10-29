import warnings

import numpy
import numpy as np

warnings.filterwarnings("ignore", category=DeprecationWarning)


import numpy as np


class AlternateRowReversed:
    """
    Context manager for a numpy 2D array whose alternate rows
    have been reversed.

    On ``__enter__``:
        Odd-indexed rows are flipped back to their original order.
        The (now un-reversed) array is returned so callers can use it
        directly::

            with AlternateRowReversed(arr) as a:
                a[1, :] = 99   # operates on the original row order

    On ``__exit__``:
        Odd-indexed rows are flipped again, restoring the
        alternate-reversed layout while keeping any mutations that were
        applied inside the context.

    Parameters
    ----------
    array : np.ndarray
        A 2-D numpy array whose odd rows (1, 3, 5, …) are stored in
        reversed column order.

    Raises
    ------
    ValueError
        If *array* is not exactly 2-dimensional.

    Example
    -------
    >>> import numpy as np
    >>> arr = np.array([[1, 2, 3],
    ...                 [6, 5, 4],   # row 1 reversed
    ...                 [7, 8, 9],
    ...                 [12, 11, 10]])  # row 3 reversed
    >>> with AlternateRowReversed(arr) as a:
    ...     print(a)          # rows in natural order
    ...     a[0, 0] = 99      # modify element in canonical space
    [[1 2 3]
     [4 5 6]
     [7 8 9]
     [10 11 12]]
    >>> print(arr)            # alternate rows re-reversed; edit preserved
    [[99  2  3]
     [ 6  5  4]
     [ 7  8  9]
     [12 11 10]]
    """

    def __init__(self, array: np.ndarray, odd: bool = False) -> None:
        self.reverse_index = 1 if odd else 0
        if array.ndim != 2:
            raise ValueError(
                f"AlternateRowReversed requires a 2-D array, got {array.ndim}-D."
            )
        self.array = array

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> np.ndarray:
        """Un-reverse alternate rows and return the array."""
        self.array[self.reverse_index::2] = self.array[self.reverse_index::2, ::-1]
        return self.array

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Re-reverse alternate rows, preserving any in-context edits."""
        self.array[self.reverse_index::2] = self.array[self.reverse_index::2, ::-1]
        return False   # do not suppress exceptions


def check_grid_quality(scores: np.ndarray, max_search_lag: int = 32) -> dict:
    """
    Evaluates raster grid interleave coherence by cross-correlating the odd
    field against the vertically interpolated even field.

    Returns:
        r0 (float): Correlation at lag 0 (1.0 = perfect alignment, <0.8 = defective).
        optimal_shift (float): Continuous sub-frame shift to align the scan.
        best_corr (float): Maximum correlation achievable after alignment.
        is_recoverable (bool): True if alignment will restore coherence (best_corr >= 0.80).
    """
    jp, ip = scores.shape
    if jp < 3 or np.nanmax(scores) <= 1.0:
        return {'r0': 1.0, 'optimal_shift': 0.0, 'best_corr': 1.0, 'is_recoverable': True}

    # Extract odd rows and vertically interpolated even neighbors
    odd_indices = np.arange(1, jp - 1, 2)
    if len(odd_indices) == 0:
        return {'r0': 1.0, 'optimal_shift': 0.0, 'best_corr': 1.0, 'is_recoverable': True}

    even_interp = np.array([(scores[j - 1] + scores[j + 1]) / 2.0 for j in odd_indices])
    odd_actual = np.array([scores[j] for j in odd_indices])

    norm_even = np.linalg.norm(even_interp)
    norm_odd = np.linalg.norm(odd_actual)
    if norm_even < 1e-4 or norm_odd < 1e-4:
        return {'r0': 0.0, 'optimal_shift': 0.0, 'best_corr': 0.0, 'is_recoverable': False}

    # Baseline coherence at zero shift
    r0 = float(np.sum(odd_actual * even_interp) / (norm_odd * norm_even))

    # 1D Horizontal cross-correlation
    max_lag = min(ip - 2, max_search_lag)
    lags = np.arange(-max_lag, max_lag + 1)
    corrs = []

    for lag in lags:
        if lag < 0:
            a, b = odd_actual[:, :ip + lag], even_interp[:, -lag:]
        elif lag > 0:
            a, b = odd_actual[:, lag:], even_interp[:, :ip - lag]
        else:
            a, b = odd_actual, even_interp

        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        c = np.sum(a * b) / (na * nb) if na > 1e-4 and nb > 1e-4 else 0.0
        corrs.append(c)

    corrs = np.array(corrs)
    best_idx = int(np.argmax(corrs))
    best_lag = lags[best_idx]
    best_corr = float(corrs[best_idx])

    # Parabolic sub-pixel peak interpolation
    if 0 < best_idx < len(corrs) - 1:
        y0, y1, y2 = corrs[best_idx - 1], corrs[best_idx], corrs[best_idx + 1]
        denom = 2.0 * (2.0 * y1 - y0 - y2)
        refined_lag = best_lag + ((y2 - y0) / denom if denom > 1e-6 else 0.0)
    else:
        refined_lag = float(best_lag)

    optimal_shift = float(abs(refined_lag) / 2.0)

    return {
        'r0': round(r0, 3),
        'optimal_shift': int(round(optimal_shift)),
        'best_corr': round(best_corr, 3),
        'is_recoverable': bool(best_corr >= 0.80)
    }


def grid_from_bounds(bbox, step_size, **kwargs):
    """
    Make a grid from a bounding box
    :param bbox: array of two points representing a 2D bounding box [(left, top), (right, bottom)]
    :param step_size: step size
    :param kwargs: extra args
    :return: array of points on the grid in order
    """

    grid_shape = calc_grid_size(bbox, step_size)
    grid_size = grid_shape * step_size

    grid_center = (bbox[1] + bbox[0]) / 2.
    grid_origin = grid_center - grid_size / 2. + step_size / 2

    nX, nY = grid_shape
    xi = numpy.arange(0, nX) * step_size + grid_origin[0]
    yi = numpy.arange(0, nY) * step_size + grid_origin[1]

    return calc_grid_coords(xi, yi, **kwargs)


def grid_from_size(size: tuple, step: float, center: tuple, **kwargs):
    """
    Make a grid from shape
    :param size: tuple (width, height) number of points in x and y directions
    :param step: step size
    :param center: center of grid in same units as step
    :param kwargs: Extra args
    :return: array of points on the grid in order
    """

    cX, cY = center
    nX, nY = size

    xi = (numpy.arange(0, nX) - (nX - 1) / 2) * step + cX
    yi = (numpy.arange(0, nY) - (nY - 1) / 2) * step + cY

    return calc_grid_coords(xi, yi, **kwargs)


def calc_grid_coords(xi, yi, snake=False, vertical=False, buggy=False):
    """
    Calculate the grid coordinates and return a properly ordered sequence based on device traversal
    :param xi: array of x coordinates
    :param yi: array of y coordinates
    :param snake: invert alternate rows/columns
    :param vertical: traverse verticaly
    :param buggy:  Fix buggy indexing for power-pmac
    :return: 3xN array of coordinates for each grid point, and a 2xN array for the corresponding
    index positions in the 2D grid, and the corresponding frame numbers for each position
    """
    x_ij, y_ij = numpy.meshgrid(xi[::-1], yi, sparse=False)
    nX, nY = len(xi), len(yi)
    ix = numpy.arange(nX).astype(int)
    jy = numpy.arange(nY).astype(int)
    i_xy, j_xy = numpy.meshgrid(ix[::-1], jy, sparse=False)

    if not vertical or nX >= nY:
        if snake:
            x_ij[1::2, :] = x_ij[1::2, ::-1]  # flip even rows
            i_xy[1::2, :] = i_xy[1::2, ::-1]  # flip even rows
        grid = numpy.array(
            [
                (x_ij[j, i], y_ij[j, i], 0.0)
                for j in jy for i in ix  # fast axis is x
            ]
        )
        index = [
            (int(j_xy[j, i]), int(i_xy[j, i]))
            for j in jy for i in ix
        ]

    else:
        if snake:
            y_ij[:, 1::2] = y_ij[::-1, 1::2]  # flip even columns
            j_xy[:, 1::2] = j_xy[::-1, 1::2]  # flip even columns
        grid = numpy.array(
            [
                (x_ij[j, i], y_ij[j, i], 0.0)
                for i in ix for j in jy  # fast axis is y
            ]
        )
        index = [
            (int(j_xy[j, i]), int(i_xy[j, i]))
            for i in ix for j in jy
        ]

    size = len(index)
    frames = numpy.arange(size)

    # some MD2s produce an extra frame every new line
    if buggy:
        frames = (frames + numpy.divmod(frames, nX)[0] + 1)
        frames[frames >= size] = size - 1

    return grid, index, frames + 1


def calc_grid_shape(width, height, aperture):
    """
    Calculate the size of the grid

    :param width: width
    :param height: height
    :param aperture: step size
    :param tight: bool, true if close fitting required
    :return: tuple (x-size, y-size)
    """
    size = numpy.array([width, height])
    nX, nY = numpy.round(size / aperture).astype(int)
    nX = max(1, nX)
    nY = max(2, nY)
    return nX, nY


def shift_rows(array: np.ndarray, offset: int, fill_value: float = 0) -> np.ndarray:
    """
    Return a new 2D array of the same shape in which every row has been
    shifted horizontally by *offset* columns.

    Columns that move outside the array boundary are dropped; the vacated
    positions are filled with *fill_value*.

    :param array: np.ndarray, source 2-D array
    :param offset: int, number of columns to shift, positive → right, negative → left, zero → no shift
    :param fill_value: float, optional, value used for positions that have no corresponding source element
    :return: np.ndarray, a new array with the same shape and dtype as *array*
    :raises ValueError: If *array* is not exactly 2-dimensional.

    Examples
    --------
    >>> import numpy as np
    >>> a = np.array([[1, 2, 3, 4],
    ...               [5, 6, 7, 8]])
    >>> shift_rows(a, 2)
    array([[0, 0, 1, 2],
           [0, 0, 5, 6]])
    >>> shift_rows(a, -1, fill_value=-1)
    array([[ 2,  3,  4, -1],
           [ 6,  7,  8, -1]])
    """
    if array.ndim != 2:
        raise ValueError(
            f"shift_rows requires a 2-D array, got {array.ndim}-D."
        )

    rows, cols = array.shape
    result = np.full(array.shape, fill_value=fill_value, dtype=array.dtype)

    if offset == 0 or abs(offset) >= cols:
        if offset == 0:
            result[:] = array
        # if |offset| >= cols every element is out of range → all fill_value
        return result

    if offset < 0:
        result[:, -offset:] = array[:, :cols + offset]
    else:
        result[:, :cols - offset] = array[:, offset:]

    return result


def calc_grid_size(bbox, step_size):
    """
    Calculate the size of the grid

    :param bbox: bounding_box coordinates in pixels
    :param step_size: step size in pixels
    :return: tuple (x-size, y-size)
    """

    grid_shape = numpy.ceil(numpy.abs(bbox[1] - bbox[0]) / step_size).astype(int)
    return numpy.maximum(grid_shape, 1)


def fix_grid(params, grid_config, max_delay=0.45):
    """
    Fix the grid configuration to ensure that the grid index and scores are consistent
    :param params: dict containing parameters, including 'exposure'
    :param grid_config: dict containing grid configuration
    :param max_delay: float, maximum delay in seconds for grid fixing
    :return: fixed grid configuration
    """

    shape = grid_config['grid_scores'].shape
    index = np.array([tuple(map(int, pair)) for pair in grid_config['grid_index']])
    grid_rows, grid_cols = index[:, 0].reshape(shape), index[:, 1].reshape(shape)

    max_lag = int(max_delay / params['exposure'])
    quality = check_grid_quality(grid_config['grid_scores'], max_search_lag=max_lag)
    with AlternateRowReversed(grid_cols) as cols:
        new_cols = shift_rows(cols, offset=quality['optimal_shift'], fill_value=-1)
        cols[...] = new_cols

    grid_index = list(zip(grid_rows.ravel(), grid_cols.ravel()))
    grid_config['grid_index'] = grid_index
    return grid_config

