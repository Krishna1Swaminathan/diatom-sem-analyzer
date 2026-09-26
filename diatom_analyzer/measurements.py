"""Per-frustule geometry: size, orientation, shape descriptors, view and morphotype."""

import math

import cv2
import numpy as np
from skimage import measure

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
    for region in measure.regionprops(labels):
        contour = _largest_contour(region.image)
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
            solidity=float(region.solidity),
            rect_fill=float(min(1.0, area / (length * width))),
            ellipse_iou=_ellipse_iou(region),
            circularity=float(min(1.0, 4 * math.pi * area / perimeter**2)),
            notch_depth_ratio=_notch_depth(contour) / width if width else 0.0,
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
