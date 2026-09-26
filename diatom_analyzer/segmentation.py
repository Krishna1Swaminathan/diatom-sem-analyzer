"""Find every frustule in the frame and return an instance label image."""

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import filters, measure, morphology, segmentation

from .config import SegmentationConfig


def _bright_background(img, threshold):
    """The class covering most of the image border is the substrate."""
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    return (border > threshold).mean() > 0.5


def _flatten_background(img, bright_bg):
    """Remove uneven illumination/charging with a quadratic fit to background pixels."""
    h, w = img.shape
    step = max(1, int(np.sqrt(h * w / 40000)))
    small = img[::step, ::step]
    t = filters.threshold_otsu(small)
    bg = small > t if bright_bg else small < t
    if bg.sum() < 50:
        return img
    yy, xx = np.mgrid[0:h:step, 0:w:step]
    yy, xx = yy[: small.shape[0], : small.shape[1]] / h, xx[: small.shape[0], : small.shape[1]] / w
    A = np.stack([np.ones_like(xx), xx, yy, xx * yy, xx**2, yy**2], -1)[bg]
    coef, *_ = np.linalg.lstsq(A, small[bg], rcond=None)
    Y, X = np.mgrid[0:h, 0:w]
    Y, X = Y / h, X / w
    surface = coef[0] + coef[1] * X + coef[2] * Y + coef[3] * X * Y + coef[4] * X**2 + coef[5] * Y**2
    return img - surface + surface.mean()


def _watershed_pieces(mask, dist, h):
    """Split ``mask`` at distance-transform peaks that stand at least ``h`` above their saddles.

    h-maxima are taken as regional maxima of the reconstruction, so a flat ridge (a linear
    pennate) stays one plateau; skimage's h_maxima marks each one-pixel bump on it separately.
    """
    rec = morphology.reconstruction(dist - h, dist, method="dilation")
    peaks = morphology.local_maxima(rec, connectivity=2) & mask
    markers, n = ndi.label(peaks, structure=np.ones((3, 3)))
    if n < 2:
        return None
    return segmentation.watershed(-dist, markers, mask=mask)


def _solidity(mask):
    props = measure.regionprops(mask.astype(np.uint8))
    return props[0].solidity if props else 0.0


def _split_touching(labels, prominence):
    out = np.zeros_like(labels)
    next_id = 1
    for region in measure.regionprops(labels):
        sl = region.slice
        mask = region.image
        pieces = None
        if region.solidity < 0.95:
            dist = ndi.distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1]
            pieces = _watershed_pieces(mask, dist, max(2.0, prominence * dist.max()))
            if pieces is None and region.solidity < 0.85:
                # A thin frustule touching a fat one has a low peak next to a high one. Try a
                # more sensitive split, kept only if it turns a non-convex blob into convex parts.
                trial = _watershed_pieces(mask, dist, max(2.0, 0.1 * dist.max()))
                if trial is not None:
                    parts = [trial == k for k in range(1, trial.max() + 1)]
                    parts = [pt for pt in parts if pt.any()]
                    if (min(pt.sum() for pt in parts) >= 0.08 * region.area
                            and min(_solidity(pt) for pt in parts) >= 0.9):
                        pieces = trial
        if pieces is None:
            out[sl][mask] = next_id
            next_id += 1
            continue
        for k in range(1, pieces.max() + 1):
            part = pieces == k
            if part.any():
                out[sl][part] = next_id
                next_id += 1
    return out


def _segment_classical(image, min_area_px, cfg, close_px):
    sigma = max(1.5, min(image.shape) / 500)
    smooth = filters.gaussian(image, sigma)
    bright_bg = _bright_background(smooth, filters.threshold_otsu(smooth))
    flat = _flatten_background(smooth, bright_bg)
    fg = flat > filters.threshold_otsu(flat)
    if bright_bg:  # dark objects on a bright substrate
        fg = ~fg
    radius = max(1, int(round(sigma)))
    fg = ndi.binary_opening(fg, structure=morphology.disk(radius))
    # Close over pore-sized gaps so pores at the margin don't carve dents into the outline.
    close = max(radius + 1, int(close_px))
    fg = ndi.binary_closing(np.pad(fg, close), structure=morphology.disk(close))[close:-close, close:-close]
    fg = ndi.binary_fill_holes(fg)
    labels = measure.label(fg)
    small = np.nonzero(np.bincount(labels.ravel()) < min_area_px)[0]
    labels[np.isin(labels, small[small > 0])] = 0
    if cfg.split_touching:
        for _ in range(3):  # a blob of three frustules may need two rounds
            split = _split_touching(labels, cfg.split_prominence)
            if split.max() == labels.max():
                break
            labels = split
    return labels


def _segment_cellpose(image, cfg):
    try:
        from cellpose import models
    except ImportError as exc:
        raise RuntimeError("Cellpose is not installed. Run `pip install cellpose` or use the classical "
                           "segmentation method.") from exc
    try:
        model = models.CellposeModel(gpu=False, model_type="cyto3")
    except TypeError:  # Cellpose >= 4 removed model_type
        model = models.CellposeModel(gpu=False)
    try:
        result = model.eval(image, diameter=None, channels=[0, 0])
    except TypeError:
        result = model.eval(image, diameter=None)
    masks = result[0]
    return np.asarray(masks, dtype=np.int32)


def detect_round_cells(image, um_per_px, cfg):
    """Round centric cells (e.g. Thalassiosira) in crowded or textured scenes.

    Each valve's rim is a bright edge (often brightest on the side facing the detector), so a
    Hough circle search over the expected diameter range finds cells that a global threshold
    merges with their neighbours or with the substrate. Returns (labels, scores).
    """
    h, w = image.shape
    d_min, d_max = cfg.cell_diameter_um
    r_min = d_min / um_per_px / 2
    r_max = d_max / um_per_px / 2
    # Work at a resolution where the smallest cell is ~12 px across its radius, for speed.
    scale = min(1.0, 12.0 / max(r_min, 1.0))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
    u8 = np.clip(small * 255, 0, 255).astype(np.uint8)
    u8 = cv2.GaussianBlur(u8, (0, 0), max(1.0, r_min * scale / 6))
    circles = cv2.HoughCircles(u8, cv2.HOUGH_GRADIENT_ALT, dp=1.5, minDist=max(4.0, 1.2 * r_min * scale),
                               param1=cfg.cell_edge_strength, param2=cfg.cell_roundness,
                               minRadius=max(3, int(r_min * scale)), maxRadius=max(4, int(np.ceil(r_max * scale))))
    labels = np.zeros((h, w), np.int32)
    if circles is None:
        return labels
    circles = circles.reshape(-1, 3) / scale
    # Strongest-first: ALT returns circles sorted by accumulator score. Paint each onto free pixels.
    next_id = 1
    for x, y, r in circles:
        disk = np.zeros((h, w), np.uint8)
        cv2.circle(disk, (int(round(x)), int(round(y))), int(round(r)), 1, -1)
        disk = disk.astype(bool)
        free = disk & (labels == 0)
        if free.sum() < 0.6 * disk.sum():
            continue  # mostly inside a cell already found: a duplicate or an inner ring
        labels[free] = next_id
        next_id += 1
    return labels


def segment_frustules(image, um_per_px=None, cfg=None, exclude_boxes=()):
    """Label image (0 = background, 1..N = frustules) for a grayscale float image.

    Objects lying mostly inside ``exclude_boxes`` (scale bar and its label) are dropped.
    """
    cfg = cfg or SegmentationConfig()
    img = image.astype(np.float32)

    if um_per_px:
        min_area_px = np.pi / 4 * (cfg.min_frustule_um / um_per_px) ** 2
        close_px = min(12, round(cfg.edge_pore_close_um / um_per_px))
    else:
        min_area_px = 5e-4 * img.size
        close_px = 3

    if cfg.method == "cellpose":
        labels = _segment_cellpose(img, cfg)
    elif cfg.method == "round_cells":
        if not um_per_px:
            raise ValueError("Round-cell detection needs the image scale (µm per pixel).")
        labels = detect_round_cells(img, um_per_px, cfg)
    else:
        labels = _segment_classical(img, min_area_px, cfg, close_px)

    areas = np.bincount(labels.ravel())
    small = np.nonzero(areas < min_area_px)[0]
    labels[np.isin(labels, small[small > 0])] = 0
    if exclude_boxes:
        inside = np.zeros(labels.shape, bool)
        for x0, y0, x1, y1 in exclude_boxes:
            inside[max(0, y0):y1, max(0, x0):x1] = True
        areas = np.bincount(labels.ravel())
        in_box = np.bincount(labels[inside].ravel(), minlength=areas.size)
        mostly_inside = np.nonzero(in_box > 0.5 * np.maximum(areas, 1))[0]
        labels[np.isin(labels, mostly_inside[mostly_inside > 0])] = 0
    relabeled, _, _ = segmentation.relabel_sequential(labels)
    return relabeled.astype(np.int32)
