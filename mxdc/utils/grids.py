import re
import sys
import pickle
import warnings
from datetime import datetime
from pathlib import Path

import numpy
import numpy as np
from scipy import ndimage
import pandas as pd
import yaml

warnings.filterwarnings("ignore", category=DeprecationWarning)


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
        'optimal_shift': round(optimal_shift, 2),
        'best_corr': round(best_corr, 3),
        'is_recoverable': bool(best_corr >= 0.80)
    }


def grid_from_bounds(bbox, step_size, **kwargs):
    """
    Make a grid from a bounding box array
    :param bbox: array of two points representing a 2D bounding box [(left, top), (right, bottom)]
    :param step_size: step size
    :param kwargs: extra args
    :return: array of points on the grid in order
    """

    grid_shape = calc_grid_size(bbox, step_size)
    grid_size = grid_shape * step_size

    grid_center = (bbox[1] + bbox[0])/2.
    grid_origin = grid_center - grid_size/2. + step_size/2

    nX, nY = grid_shape
    xi = numpy.arange(0, nX)*step_size + grid_origin[0]
    yi = numpy.arange(0, nY)*step_size + grid_origin[1]

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
    radius = step / 2

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
    i_xy, j_xy =  numpy.meshgrid(ix[::-1], jy, sparse=False)

    if not vertical or nX >= nY:
        if snake:
            x_ij[1::2, :] = x_ij[1::2, ::-1]  # flip even rows
            i_xy[1::2, :] = i_xy[1::2, ::-1]  # flip even rows
        grid = numpy.array([
            (x_ij[j, i], y_ij[j, i], 0.0)
            for j in jy for i in ix  # fast axis is x
        ])
        index = [
            (j_xy[j, i], i_xy[j, i])
            for j in jy for i in ix
        ]

    else:
        if snake:
            y_ij[:, 1::2] = y_ij[::-1, 1::2]  # flip even columns
            j_xy[:, 1::2] = j_xy[::-1, 1::2]  # flip even columns
        grid = numpy.array([
            (x_ij[j, i], y_ij[j, i], 0.0)
            for i in ix for j in jy  # fast axis is y
        ])
        index = [
            (j_xy[j, i], i_xy[j, i])
            for i in ix for j in jy
        ]

    size = len(index)
    frames = numpy.arange(size)

    # some MD2s produce an extra frame every new line
    if buggy:
        frames = (frames + numpy.divmod(frames, nX)[0] + 1)
        frames[frames>=size] = size-1

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


def calc_grid_size(bbox, step_size):
    """
    Calculate the size of the grid

    :param bbox: bounding_box coordinates in pixels
    :param step_size: step size in pixels
    :return: tuple (x-size, y-size)
    """

    grid_shape = numpy.ceil(numpy.abs(bbox[1] - bbox[0])/step_size).astype(int)
    return numpy.maximum(grid_shape, 1)
