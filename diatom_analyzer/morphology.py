"""Opening and closing with a round element of any radius, in time independent of the radius.

Uses distance transforms instead of sliding a disk over the image, which matters for the large,
radius-relative smoothing applied to big frustules.
"""

import cv2
import numpy as np


def _distance(mask):
    return cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def dilate(mask, r):
    return _distance(~mask) <= r


def erode(mask, r):
    return _distance(mask) > r


def opening(mask, r):
    """Remove parts narrower than a disk of radius r (edges are treated as background)."""
    if r < 1:
        return mask
    return dilate(erode(mask, r), r)


def closing(mask, r, pad=True):
    """Fill gaps and slits narrower than a disk of radius r."""
    if r < 1:
        return mask
    if pad:
        p = int(np.ceil(r)) + 2
        work = np.pad(mask, p)
        return erode(dilate(work, r), r)[p:-p, p:-p]
    return erode(dilate(mask, r), r)
