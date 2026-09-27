"""Manual corrections: add a missed frustule, or remove a false detection.

To add a frustule, drag along its long axis from tip to tip (or click once on a round one). The
outline is traced by a marker watershed on the edge strength: the dragged axis seeds the frustule,
the area beyond its tips and far to either side seeds the background, and the region grows until
it meets the frustule's own edges. On greyscale SEM images, where neighbouring cells have the same
brightness, edges separate them far better than intensity does.

Edits are stored as ``(op, x1, y1, x2, y2, size_px)`` tuples and replayed on top of the automatic
detection, so an analysis with corrections is reproducible from the image plus the list. The
corrected label images double as training data for a segmentation model (Cellpose format).
"""

from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import filters, segmentation

from . import morphology as fast_morph

MIN_DRAG_PX = 8  # shorter drags are treated as clicks


def _segment_distance(xx, yy, p, q):
    """Distance of each pixel to segment p-q, and its position t along it (0 at p, 1 at q)."""
    p, q = np.asarray(p, float), np.asarray(q, float)
    d = q - p
    t = np.clip(((xx - p[0]) * d[0] + (yy - p[1]) * d[1]) / max(float(d @ d), 1e-9), 0, 1)
    return np.hypot(xx - (p[0] + t * d[0]), yy - (p[1] + t * d[1])), t


def _grow(image, labels, box, seed, background):
    """Marker watershed on edge strength inside ``box``; returns the seed's region (full size)."""
    h, w = image.shape
    x0, y0, x1, y1 = box
    crop = image[y0:y1, x0:x1]
    edges = filters.sobel(filters.gaussian(crop, 1.5))
    markers = np.zeros(crop.shape, np.int32)
    markers[background] = 2
    markers[labels[y0:y1, x0:x1] > 0] = 2  # never overlap an existing frustule
    markers[seed] = 1
    region = segmentation.watershed(edges, markers) == 1
    region = ndi.binary_opening(ndi.binary_fill_holes(region), iterations=2)
    region &= labels[y0:y1, x0:x1] == 0
    mask = np.zeros((h, w), bool)
    mask[y0:y1, x0:x1] = region
    return mask


def _smooth(mask, seed, axis, length):
    """Trim debris and neighbours' edges that the watershed let in.

    They join the frustule through narrow necks, so an opening at a fifth of the frustule's mean
    width cuts them off; the piece holding the dragged axis is kept, and so are trimmed pieces lying
    on the axis (tapering apices). Skipped if it would remove more than a third of the area.
    """
    area = int(mask.sum())
    width = area / max(length, 1.0)
    r = 0.2 * width
    if r < 1.5:
        return mask
    p = int(np.ceil(r)) + 2
    filled = ndi.binary_fill_holes(mask)
    work = fast_morph.opening(np.pad(filled, p), r)[p:-p, p:-p]
    trimmed, _ = ndi.label(filled & ~work)
    tips = np.unique(trimmed[axis & (trimmed > 0)])
    work |= np.isin(trimmed, tips[tips > 0])
    work = fast_morph.closing(work, 0.5 * r)
    comp, _ = ndi.label(work)
    keep = np.unique(comp[seed & (comp > 0)])
    if not len(keep):
        return mask
    sizes = np.bincount(comp.ravel())
    work = comp == keep[np.argmax(sizes[keep])]
    return work if work.sum() >= area * 2 / 3 else mask


def outline_along(image, labels, p, q):
    """Frustule whose long axis runs from p to q (pixel coordinates)."""
    h, w = image.shape
    length = max(float(np.hypot(q[0] - p[0], q[1] - p[1])), MIN_DRAG_PX)
    pad = int(0.7 * length) + 4
    x0, x1 = max(0, int(min(p[0], q[0])) - pad), min(w, int(max(p[0], q[0])) + pad + 1)
    y0, y1 = max(0, int(min(p[1], q[1])) - pad), min(h, int(max(p[1], q[1])) + pad + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d, t = _segment_distance(xx, yy, p, q)
    background = (d >= 0.5 * length) | (((t <= 0) | (t >= 1)) & (d >= 0.08 * length))
    seed = (d <= 1.5) & (t > 0.04) & (t < 0.96)  # leave the tips free to find the apex edges
    mask = _grow(image, labels, (x0, y0, x1, y1), seed, background)
    full_seed, axis = np.zeros_like(mask), np.zeros_like(mask)
    full_seed[y0:y1, x0:x1] = seed
    ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
    along = ((xx - p[0]) * ux + (yy - p[1]) * uy) / length
    across = np.abs((xx - p[0]) * uy - (yy - p[1]) * ux)
    axis[y0:y1, x0:x1] = (across <= 1.5) & (along > -0.2) & (along < 1.2)  # the drag line, a little past the tips
    return _smooth(mask, full_seed, axis, length) & (labels == 0)


def outline_at(image, labels, x, y, size_px):
    """Round frustule around a single click, roughly ``size_px`` across."""
    h, w = image.shape
    r = max(4.0, size_px / 2)
    half = int(round(1.4 * r)) + 2
    x0, x1 = max(0, int(x) - half), min(w, int(x) + half + 1)
    y0, y1 = max(0, int(y) - half), min(h, int(y) + half + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist = np.hypot(xx - x, yy - y)
    return _grow(image, labels, (x0, y0, x1, y1), dist <= max(2.0, 0.3 * r), dist >= 1.25 * r)


def label_at(labels, x, y, search_px=12):
    """Label under (x, y), or the nearest one within ``search_px`` (0 if none)."""
    h, w = labels.shape
    xi, yi = int(round(x)), int(round(y))
    if 0 <= yi < h and 0 <= xi < w and labels[yi, xi]:
        return int(labels[yi, xi])
    y0, y1 = max(0, yi - search_px), min(h, yi + search_px + 1)
    x0, x1 = max(0, xi - search_px), min(w, xi + search_px + 1)
    window = labels[y0:y1, x0:x1]
    if not window.any():
        return 0
    ys, xs = np.nonzero(window)
    k = np.argmin(np.hypot(xs + x0 - x, ys + y0 - y))
    return int(window[ys[k], xs[k]])


def apply_edits(image, labels, edits):
    """Replay edits in order. Returns (labels, set of label ids that were added by hand)."""
    labels = labels.copy()
    manual = set()
    for op, x1, y1, x2, y2, size_px in edits:
        if op == "remove":
            target = label_at(labels, x1, y1)
            if target:
                labels[labels == target] = 0
                manual.discard(target)
        elif op == "add":
            if np.hypot(x2 - x1, y2 - y1) >= MIN_DRAG_PX:
                mask = outline_along(image, labels, (x1, y1), (x2, y2))
            else:
                mask = outline_at(image, labels, x1, y1, size_px)
            if mask.sum() >= 16:
                new_id = int(labels.max()) + 1
                labels[mask] = new_id
                manual.add(new_id)
    return labels, manual


def save_training_example(image, labels, folder, stem):
    """Write ``stem.png`` (image) and ``stem_masks.png`` (16-bit labels): Cellpose's training layout."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / f"{stem}.png"), np.clip(image * 255, 0, 255).astype(np.uint8))
    cv2.imwrite(str(folder / f"{stem}_masks.png"), labels.astype(np.uint16))
    return folder / f"{stem}.png", folder / f"{stem}_masks.png"
