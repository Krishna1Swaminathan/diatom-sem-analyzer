"""Per-frustule geometry: size, orientation, shape descriptors, view and morphotype."""

import math

import cv2
import numpy as np
from scipy import ndimage as ndi
from scipy.ndimage import gaussian_filter1d
from skimage import measure

from . import morphology as fast_morph
from .config import ViewConfig
from .models import Frustule


def _largest_contour(mask):
    padded = np.pad(mask.astype(np.uint8), 1)
    contours, _ = cv2.findContours(padded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv2.contourArea)
    return contour - 1


def _orientation_deg(region):
    """Long-axis angle, degrees counter-clockwise from the image x-axis (0-180)."""
    mu = region.moments_central
    mu20, mu02, mu11 = mu[2, 0], mu[0, 2], mu[1, 1]  # skimage: [row-order, col-order]
    # moments_central[p, q] = sum (r - r0)^p (c - c0)^q, so x = column, y = row
    theta = 0.5 * math.atan2(2 * mu11, mu02 - mu20)  # angle from x toward +row (downwards)
    return (-math.degrees(theta)) % 180.0


def _ellipse_iou(region):
    mask = region.image
    h, w = mask.shape
    major, minor = region.axis_major_length, region.axis_minor_length
    if major <= 0 or minor <= 0:
        return 0.0
    cy, cx = region.centroid_local
    angle = _orientation_deg(region)
    pad = int(major)
    canvas = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    cv2.ellipse(canvas, ((cx + pad, cy + pad), (major, minor), -angle), 1, -1)
    ellipse = canvas[pad:pad + h, pad:pad + w].astype(bool)
    outside = canvas.sum() - ellipse.sum()
    inter = np.logical_and(ellipse, mask).sum()
    union = np.logical_or(ellipse, mask).sum() + outside
    return float(inter / union) if union else 0.0


def _notch_depth(contour):
    if len(contour) < 5:
        return 0.0
    try:
        hull = cv2.convexHull(contour, returnPoints=False)
        defects = cv2.convexityDefects(contour, hull)
    except cv2.error:
        return 0.0
    if defects is None:
        return 0.0
    return float(np.asarray(defects).reshape(-1, 4)[:, 3].max()) / 256.0


def _sharpest_inward_corner(contour, window=0.02, ignore=None):
    """Largest inward (concave) turn of the outline, in degrees, over ~2 % of the perimeter.

    Intact valves have smooth outlines; even concave margins (crescent-shaped species) bend
    gradually. Fracture edges meet the natural margin at sharp re-entrant corners.
    ``ignore`` is a boolean mask (in the contour's coordinates) of outline stretches to skip,
    such as the cut where two touching frustules were separated.
    """
    pts = contour[:, 0, :].astype(float)
    n = len(pts)
    if n < 40:
        return 0.0
    skip = None
    if ignore is not None and ignore.any():
        xi, yi = contour[:, 0, 0], contour[:, 0, 1]
        skip = ignore[np.clip(yi, 0, ignore.shape[0] - 1), np.clip(xi, 0, ignore.shape[1] - 1)]
    sigma = max(1.0, n / 400)
    pts = np.stack([gaussian_filter1d(pts[:, 0], sigma, mode="wrap"),
                    gaussian_filter1d(pts[:, 1], sigma, mode="wrap")], -1)
    s = max(3, int(window * n))
    v1 = pts - np.roll(pts, s, 0)
    v2 = np.roll(pts, -s, 0) - pts
    turn = np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(1))
    outward = np.sign(turn.sum()) or 1.0  # a closed outline turns 360° in its convex direction
    inward = -turn * outward
    if skip is not None:
        # the turn at a point uses neighbours s steps away, so blank a window around the cut
        m = 2 * s  # the turn uses points s away, and the merged neck was rounded before the cut
        near = np.convolve(np.concatenate([skip[-m:], skip, skip[:m]]).astype(float),
                           np.ones(2 * m + 1), mode="same")[m:-m] > 0
        inward = np.where(near, 0.0, inward)
    return float(np.degrees(inward.max()))


def _damage_view(mask, width):
    """The outline as the damage tests see it: attachments narrower than ~30 % of the width removed.

    Debris stuck to a valve makes deep notches and sharp inward corners where it joins, yet is far
    narrower than the valve; a real break removes a large piece and survives this smoothing.
    Measurements (length, width, area) still use the full outline.
    """
    r = int(round(0.15 * width))
    if r < 2:
        return mask
    opened = fast_morph.opening(np.pad(mask, 1), r)[1:-1, 1:-1]
    comp, n = ndi.label(opened)
    if not n:
        return mask
    sizes = np.bincount(comp.ravel())
    sizes[0] = 0
    main = comp == int(np.argmax(sizes))
    return main if main.sum() >= 0.5 * mask.sum() else mask


def classify_view(fr, cfg):
    if fr.rect_fill >= cfg.girdle_rect_fill:
        return "girdle"
    if fr.rect_fill <= cfg.valve_rect_fill:
        return "valve"
    return "uncertain"


def classify_morphotype(fr, cfg):
    if fr.damage == "fragmented":
        return "fragment"
    if fr.view == "girdle":
        return "girdle view"
    aspect = fr.aspect_ratio
    if aspect < 1.2:
        return "centric"
    if aspect >= 4.0:
        return "pennate (linear)"
    return "pennate (elliptic)"


def measure_frustules(labels, analysis_shape=None, exclude_boxes=()):
    h, w = analysis_shape or labels.shape
    frustules = []
    others = labels > 0
    for region in measure.regionprops(labels):
        contour = _largest_contour(region.image)
        r0, c0, r1, c1 = region.bbox
        # outline pixels next to another frustule: separation cuts, not natural margins
        pad = 3
        window = labels[max(0, r0 - pad):r1 + pad, max(0, c0 - pad):c1 + pad]
        neighbour = others[max(0, r0 - pad):r1 + pad, max(0, c0 - pad):c1 + pad] & (window != region.label)
        contact = cv2.dilate(neighbour.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        contact = contact[r0 - max(0, r0 - pad):, c0 - max(0, c0 - pad):][: r1 - r0, : c1 - c0]
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour.astype(np.float32))
        length, width = max(rw, rh) + 1.0, min(rw, rh) + 1.0  # +1: pixel centres -> pixel edges
        area = float(region.area)
        perimeter = float(region.perimeter) or 1.0
        min_r, min_c, max_r, max_c = region.bbox
        touches = min_r == 0 or min_c == 0 or max_r >= h or max_c >= w
        for x0, y0, x1, y1 in exclude_boxes:
            if not (max_c < x0 or min_c > x1 or max_r < y0 or min_r > y1):
                touches = True
        aspect = length / width if width else 1.0
        damage_mask = _damage_view(region.image, width)
        damage_contour = _largest_contour(damage_mask) if damage_mask is not region.image else contour
        damage_region = measure.regionprops(damage_mask.astype(np.uint8))[0]
        cy, cx = region.centroid
        fr = Frustule(
            frustule_id=region.label,
            bbox=region.bbox,
            centroid_px=(float(cx), float(cy)),
            area_px=area,
            length_px=float(length),
            width_px=float(width),
            equiv_diameter_px=float(region.equivalent_diameter_area),
            orientation_deg=None,
            solidity=float(damage_region.solidity),
            rect_fill=float(min(1.0, area / (length * width))),
            ellipse_iou=_ellipse_iou(region),
            circularity=float(min(1.0, 4 * math.pi * area / perimeter**2)),
            notch_depth_ratio=_notch_depth(damage_contour) / width if width else 0.0,
            inward_corner_deg=_sharpest_inward_corner(damage_contour, window=0.04, ignore=contact),
            touches_border=bool(touches),
        )
        if aspect >= ViewConfig().round_aspect:
            fr.orientation_deg = _orientation_deg(region)
        frustules.append(fr)
    return frustules


def frustule_axes(fr):
    """Unit vectors (along, across) of the frustule frame in image (x right, y down) coords."""
    theta = math.radians(fr.orientation_deg or 0.0)
    along = np.array([math.cos(theta), -math.sin(theta)])
    across = np.array([math.sin(theta), math.cos(theta)])
    return along, across
