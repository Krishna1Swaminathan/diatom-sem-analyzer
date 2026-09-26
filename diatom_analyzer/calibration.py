"""Physical scale (µm per pixel) from instrument metadata or the burned-in scale bar.

Nothing in this module assumes a pixel size: every value comes from the file itself, the
image content, or the user.
"""

import io
import math
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import tifffile

from .models import Calibration

UNIT_TO_UM = {"pm": 1e-6, "nm": 1e-3, "um": 1.0, "µm": 1.0, "μm": 1.0, "micron": 1.0, "microns": 1.0,
              "mm": 1e3, "cm": 1e4, "m": 1e6}

# OCR frequently renders the micro sign as u, y, p, or a Greek mu; "pm" is never used on SEM bars.
_LABEL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(nm|mm|[µμuyp]\s?m)\b", re.IGNORECASE)
_HFW_RE = re.compile(r"HFW\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(nm|mm|[µμuyp]\s?m)", re.IGNORECASE)

# Real SEM pixels are far smaller than this; bigger values mean a screen-DPI tag, not a calibration.
_MAX_PLAUSIBLE_UM_PER_PX = 5.0


def _unit_factor(unit):
    u = unit.lower().replace(" ", "")
    if u in ("nm", "mm"):
        return UNIT_TO_UM[u]
    if u.endswith("m") and len(u) == 2:
        return 1.0
    return UNIT_TO_UM.get(u)


def _parse_number(text):
    return float(text.replace(",", "."))


# --------------------------------------------------------------------------- metadata


def _from_fei(tif):
    meta = tif.fei_metadata
    if not meta:
        return None
    for section in ("Scan", "EScan", "Image"):
        value = meta.get(section, {}).get("PixelWidth")
        if value:
            return float(value) * 1e6, "metadata:FEI/Thermo", {"PixelWidth_m": float(value)}
    return None


def _from_zeiss(tif):
    meta = tif.sem_metadata
    if not meta:
        return None
    for key in ("ap_image_pixel_size", "ap_pixel_size"):
        entry = meta.get(key)
        if not entry:
            continue
        parts = entry if isinstance(entry, (tuple, list)) else (entry,)
        text = " ".join(str(p) for p in parts[1:] if p is not None) or str(parts[0])
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(pm|nm|µm|um|μm|mm)", text)
        if m:
            factor = _unit_factor(m.group(2))
            return _parse_number(m.group(1)) * factor, "metadata:Zeiss", {key: text}
    return None


def _from_imagej_or_resolution(tif):
    page = tif.pages[0]
    xres = page.tags.get("XResolution")
    if xres is None:
        return None
    num, den = xres.value
    if not num or not den:
        return None
    px_per_unit = num / den
    ij = tif.imagej_metadata or {}
    unit = str(ij.get("unit", "")).strip()
    if unit:
        factor = _unit_factor(unit.replace("\\u00B5", "µ"))
        if factor:
            return factor / px_per_unit, "metadata:ImageJ", {"unit": unit, "px_per_unit": px_per_unit}
    res_unit = page.tags.get("ResolutionUnit")
    if res_unit is not None and int(res_unit.value) == 3:  # centimetre
        um = 1e4 / px_per_unit
        if um <= _MAX_PLAUSIBLE_UM_PER_PX:
            return um, "metadata:TIFF resolution", {"px_per_cm": px_per_unit}
    return None


def _from_sidecar(path):
    """JEOL and Hitachi instruments write calibration into a .txt next to the image."""
    if path is None:
        return None
    for candidate in (Path(path).with_suffix(".txt"), Path(path).with_suffix(".TXT")):
        if not candidate.exists():
            continue
        text = candidate.read_text(errors="ignore")
        m = re.search(r"^\s*PixelSize\s*=\s*([\d.]+)", text, re.MULTILINE)
        if m:  # Hitachi: nanometres per pixel
            return float(m.group(1)) * 1e-3, "metadata:Hitachi .txt", {"PixelSize_nm": float(m.group(1))}
        bar = re.search(r"\$\$SM_MICRON_BAR\s+([\d.]+)", text)
        marker = re.search(r"\$\$SM_MICRON_MARKER\s+([\d.]+)\s*(nm|um|µm|mm)", text, re.IGNORECASE)
        if bar and marker:  # JEOL: bar length in px and the length it represents
            um = _parse_number(marker.group(1)) * _unit_factor(marker.group(2))
            return um / float(bar.group(1)), "metadata:JEOL .txt", {"bar_px": float(bar.group(1)), "marker": marker.group(0)}
    return None


def calibration_from_metadata(path=None, data=None):
    """Return (um_per_px, source, details) from embedded metadata, or None."""
    sidecar = _from_sidecar(path)
    if sidecar:
        return sidecar
    try:
        handle = tifffile.TiffFile(io.BytesIO(data) if data is not None else path)
    except Exception:
        return None
    with handle as tif:
        for reader in (_from_fei, _from_zeiss, _from_imagej_or_resolution):
            try:
                result = reader(tif)
            except Exception:
                result = None
            if result and 0 < result[0] <= _MAX_PLAUSIBLE_UM_PER_PX:
                return result
    return None


# --------------------------------------------------------------------------- databar


def find_databar_top(image):
    """Row index where the instrument's information strip starts (image height if none).

    Databars are synthetic overlays: most pixels in each of their rows share one exact value,
    which almost never happens in a noisy micrograph row.
    """
    h, w = image.shape
    q = np.round(image * 255).astype(np.uint8)
    flat = np.array([np.bincount(row, minlength=256).max() / w >= 0.5 for row in q])
    if flat[-5:].sum() < 3:
        return h
    top, gap, y = h, 0, h - 1
    limit = int(h * 0.65)
    while y >= limit:
        if flat[y]:
            top, gap = y, 0
        else:
            gap += 1
            if gap > max(3, h // 200):
                break
        y -= 1
    band = h - top
    return top if band >= max(8, 0.02 * h) else h


# --------------------------------------------------------------------------- scale bar


def find_scale_bar_candidates(image, search_top=0):
    """Long, thin, solid, isolated horizontal bars. Returns dicts sorted best-first."""
    h, w = image.shape
    min_len = max(20, int(0.025 * w))
    max_thick = max(3, int(0.03 * h))
    candidates = []
    for polarity, binary in (("bright", image >= 0.8 * image.max()), ("dark", image <= 0.15)):
        binary = binary.astype(np.uint8)
        binary[:search_top] = 0
        _, parents, parent_stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, min_len), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if bw < min_len or bw > 0.6 * w or bh > max_thick or bw / max(bh, 1) < 5:
                continue
            fill = area / float(bw * bh)
            if fill < 0.8:
                continue
            # The bar must stand alone (end ticks allowed): a straight run that is part of a
            # larger bright shape, such as the rim of a frustule, is not a scale bar.
            ys, xs = np.nonzero(labels[y:y + bh, x:x + bw] == i)
            parent = parents[y + ys[0], x + xs[0]]
            _, _, pw, ph, _ = parent_stats[parent]
            if pw > 1.15 * bw + 4 or ph > max(4 * bh + 4, 0.3 * bw):
                continue
            # Prefer bars low in the frame, where instruments put them, and crisp ones.
            score = fill + 0.5 * (y / h) + (0.3 if polarity == "bright" else 0.0)
            candidates.append({"bbox": (int(x), int(y), int(x + bw), int(y + bh)), "length_px": float(bw),
                               "polarity": polarity, "score": score})
    candidates.sort(key=lambda c: -c["score"])
    return candidates


def ocr_available():
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None or _tesseract_cmd_configured()


def _tesseract_cmd_configured():
    try:
        import pytesseract
        return Path(pytesseract.pytesseract.tesseract_cmd).exists()
    except Exception:
        return False


def _ocr(region):
    import pytesseract
    texts = []
    up = cv2.resize((region * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:
        bw = 255 - bw  # tesseract wants dark text on a light page
    for psm in (7, 6, 11):
        try:
            texts.append(pytesseract.image_to_string(bw, config=f"--psm {psm}"))
        except Exception:
            continue
    return texts


def _is_round_value(value):
    """Scale bars are labelled with round numbers: 1, 2, 2.5, 3, 5 times a power of ten."""
    if value <= 0:
        return False
    mantissa = value / 10 ** math.floor(math.log10(value))
    return any(abs(mantissa - m) < 1e-6 for m in (1, 2, 2.5, 3, 4, 5))


def read_bar_label(image, bbox):
    """OCR the text near a scale bar and return (length_um, raw_text) or (None, raw_text).

    Labels are almost always centred above or below the bar, so those narrow regions are
    tried first; text beside the bar (JEOL style) is the fallback, taking the match nearest
    the bar so other databar fields (working distance, HV) are not mistaken for the label.
    """
    h, w = image.shape
    x0, y0, x1, y1 = bbox
    bar_len = x1 - x0
    text_h = max(14, int(0.035 * h), 3 * (y1 - y0))
    margin = max(4, bar_len // 10)
    regions = [
        ("above", max(0, y0 - 3 * text_h), y0, max(0, x0 - margin), min(w, x1 + margin)),
        ("below", y1, min(h, y1 + 3 * text_h), max(0, x0 - margin), min(w, x1 + margin)),
        ("right", max(0, y0 - text_h), min(h, y1 + text_h), min(w, x1 + 2), min(w, x1 + bar_len)),
        ("left", max(0, y0 - text_h), min(h, y1 + text_h), max(0, x0 - bar_len), max(0, x0 - 2)),
    ]
    seen = []
    for side, ra, rb, ca, cb in regions:
        if rb - ra < 6 or cb - ca < 6:
            continue
        for text in _ocr(image[ra:rb, ca:cb]):
            seen.append(text.strip())
            matches = [m for m in _LABEL_RE.finditer(text) if _parse_number(m.group(1)) > 0]
            if not matches:
                continue
            m = matches[-1] if side == "left" else matches[0]
            return _parse_number(m.group(1)) * _unit_factor(m.group(2)), m.group(0)
    return None, " | ".join(t for t in seen if t)


def read_hfw(image, databar_top):
    """FEI/Thermo databars print the horizontal field width; µm/px = HFW / image width."""
    if databar_top >= image.shape[0]:
        return None
    for text in _ocr(image[databar_top:]):
        m = _HFW_RE.search(text)
        if m:
            return _parse_number(m.group(1)) * _unit_factor(m.group(2)) / image.shape[1], m.group(0)
    return None


# --------------------------------------------------------------------------- orchestration


def calibrate(image, path=None, data=None, manual_um_per_px=None, manual_bar_um=None, use_ocr=True):
    """Work out µm/px. Priority: user override, metadata, scale bar (+OCR), HFW text."""
    databar_top = find_databar_top(image)
    bars = find_scale_bar_candidates(image)
    bar = bars[0] if bars else None
    details = {"databar_top": databar_top, "bar_candidates": len(bars)}

    def _cal(um, source, **extra):
        cal = Calibration(um_per_px=um, source=source, details={**details, **extra})
        if bar:
            cal.scale_bar_bbox = bar["bbox"]
            cal.scale_bar_length_px = bar["length_px"]
        return cal

    if manual_um_per_px:
        return _cal(float(manual_um_per_px), "manual")
    if manual_bar_um and bar:
        return _cal(float(manual_bar_um) / bar["length_px"], "scale_bar (user-entered label)",
                    bar_um=float(manual_bar_um))

    meta = calibration_from_metadata(path, data) if (path is not None or data is not None) else None

    bar_um, label = None, None
    can_ocr = use_ocr and ocr_available()
    if bar and can_ocr:
        bar_um, label = read_bar_label(image, bar["bbox"])
        if bar_um and bar_um / bar["length_px"] > _MAX_PLAUSIBLE_UM_PER_PX:
            label = f"{label} (rejected: implies {bar_um / bar['length_px']:.3g} µm/px)"
            bar_um = None
        elif bar_um and not _is_round_value(_parse_number(_LABEL_RE.search(label).group(1))):
            details["warning"] = (f"The scale bar label was read as '{label}', which is not a usual "
                                  "scale-bar value. Please check it in the Scale calibration tab.")

    if meta:
        cal = _cal(meta[0], meta[1], **meta[2])
        if bar_um:
            from_bar = bar_um / bar["length_px"]
            cal.details["scale_bar_um_per_px"] = from_bar
            disagreement = abs(from_bar - meta[0]) / meta[0]
            if disagreement > 0.05:
                cal.details["warning"] = (
                    f"Metadata ({meta[0]:.4g} µm/px) and scale bar ({from_bar:.4g} µm/px) disagree by "
                    f"{disagreement:.0%}. The image may have been resized after acquisition.")
        cal.label_text = label
        return cal

    if bar_um:
        cal = _cal(bar_um / bar["length_px"], "scale_bar", bar_um=bar_um)
        cal.label_text = label
        return cal

    if can_ocr:
        hfw = read_hfw(image, databar_top)
        if hfw:
            return _cal(hfw[0], "databar HFW text", hfw_text=hfw[1])

    reason = "no scale bar found" if not bar else (
        "scale bar found but OCR is not installed" if not can_ocr else f"could not read bar label ({label!r})")
    cal = _cal(None, "none", reason=reason)
    cal.label_text = label
    return cal
