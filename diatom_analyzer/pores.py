"""Pore (areola) detection inside each frustule, plus crack candidates for damage grading.

Pores are dark depressions in the bright silica shell. The local shell level comes from a
high-percentile rank filter (robust to the bright edge effect at the rim and to porosities up to
~70%). Each pore's extent is taken at half its depth, the image-analysis equivalent of
full-width-at-half-maximum, so diameters don't depend on the detection threshold.
"""

import numpy as np
from scipy import ndimage as ndi
from skimage import filters, measure, morphology, segmentation
from skimage.filters import rank

from .config import PoreConfig
from .measurements import frustule_axes
from .models import Pore


def _noise_sigma(values):
    d = np.diff(values)
    if d.size < 10:
        return 0.01
    return float(np.median(np.abs(d - np.median(d))) / 0.6745 / np.sqrt(2)) or 0.01


def _shell_level(crop, mask, radius):
    """70th-percentile brightness in a disk, computed on a downsampled copy for speed."""
    fill = np.median(crop[mask])
    work = np.where(mask, crop, fill)
    factor = max(1, int(radius // 12))
    small = work[::factor, ::factor]
    u8 = np.clip(small * 255, 0, 255).astype(np.uint8)
    r = max(3, int(round(radius / factor)))
    level = rank.percentile(u8, morphology.disk(r), p0=0.7).astype(np.float32) / 255
    if factor > 1:
        level = ndi.zoom(level, (crop.shape[0] / level.shape[0], crop.shape[1] / level.shape[1]), order=1)
        level = level[: crop.shape[0], : crop.shape[1]]
        if level.shape != crop.shape:
            level = np.pad(level, [(0, crop.shape[0] - level.shape[0]), (0, crop.shape[1] - level.shape[1])],
                           mode="edge")
    return level


def detect_pores(image, labels, fr, um_per_px, cfg=None):
    """Return (pores, crack_candidates) for one frustule.

    crack_candidates is a list of lengths in px of long, thin dark features.
    """
    cfg = cfg or PoreConfig()
    r0, c0, r1, c1 = fr.bbox
    pad = 4
    r0p, c0p = max(0, r0 - pad), max(0, c0 - pad)
    r1p, c1p = min(labels.shape[0], r1 + pad), min(labels.shape[1], c1 + pad)
    crop = image[r0p:r1p, c0p:c1p].astype(np.float32)
    mask = labels[r0p:r1p, c0p:c1p] == fr.frustule_id
    if mask.sum() < 50:
        return [], []

    if um_per_px:
        max_d_px = cfg.max_diameter_um / um_per_px
        min_d_px = cfg.min_diameter_um / um_per_px
    else:
        max_d_px, min_d_px = 0.1 * fr.width_px, 1.5
    max_d_px = max(3.0, min(max_d_px, cfg.max_fraction_of_width * fr.width_px))
    min_d_px = max(1.2, min_d_px)

    smooth = filters.gaussian(crop, 0.7)
    level = _shell_level(smooth, mask, radius=max(6.0, 1.5 * max_d_px))
    # Two pixels in from the outline, the smoothed edge blends with the substrate and looks "dark".
    inner = ndi.binary_erosion(mask, iterations=2)
    depth = np.where(inner, level - smooth, 0.0)

    shell = float(np.median(level[mask]))
    noise = _noise_sigma(crop[mask])
    scale = max(0.2, cfg.contrast_k / 0.5)
    t_high = max(5 * noise, 0.15 * shell) * scale
    t_low = max(2.5 * noise, 0.07 * shell) * scale
    candidates = filters.apply_hysteresis_threshold(depth, t_low, t_high) & inner
    comp = measure.label(candidates)
    if comp.max() == 0:
        return [], []

    crack_len_min = max(8.0, 0.15 * fr.length_px)
    cracks, crack_ids = [], []
    for region in measure.regionprops(comp):
        major, minor = region.axis_major_length, max(region.axis_minor_length, 1.0)
        if major >= crack_len_min and major / minor >= 4:
            cracks.append(float(major))
            crack_ids.append(region.label)
    in_crack = np.isin(comp, crack_ids) if crack_ids else np.zeros_like(inner)

    # Re-threshold every candidate at half its own peak depth (FWHM-style extent).
    peak = ndi.maximum(depth, comp, index=np.arange(comp.max() + 1))
    grown = segmentation.expand_labels(comp, distance=3) * inner
    half = depth >= 0.5 * np.asarray(peak)[grown]
    pore_labels = measure.label((grown > 0) & half)

    rim = inner & ~ndi.binary_erosion(inner, iterations=1)
    along_v, across_v = frustule_axes(fr)
    cx, cy = fr.centroid_px

    pores = []
    for region in measure.regionprops(pore_labels):
        if region.area < cfg.min_area_px:
            continue
        coords = region.coords
        touches_rim = rim[coords[:, 0], coords[:, 1]].any()
        major = region.axis_major_length
        minor = max(region.axis_minor_length, 1.0)
        on_crack = in_crack[coords[:, 0], coords[:, 1]].mean() > 0.5
        if on_crack and major / minor >= 2.5:
            continue  # a piece of the crack line itself
        d = region.equivalent_diameter_area
        if touches_rim or d < min_d_px or d > max_d_px:
            continue
        y, x = region.centroid
        x_abs, y_abs = x + c0p, y + r0p
        offset = np.array([x_abs - cx, y_abs - cy])
        pores.append(Pore(pore_id=len(pores) + 1, x_px=float(x_abs), y_px=float(y_abs), diameter_px=float(d),
                          area_px=float(region.area), major_px=float(major), minor_px=float(minor),
                          along_px=float(offset @ along_v), across_px=float(offset @ across_v)))
    return pores, cracks
