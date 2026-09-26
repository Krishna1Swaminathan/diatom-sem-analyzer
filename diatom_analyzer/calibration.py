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
from skimage import filters

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
    if u.endswith("m") and 2 <= len(u) <= 3 and all(c in "µμuyp" for c in u[:-1]):
        return 1.0  # micrometre, however the OCR spelled the micro sign
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


# Hitachi S-series magnification is referenced to a 127 mm (5-inch photo) wide field of view.
HITACHI_REFERENCE_WIDTH_UM = 127_000.0


def parse_sidecar_text(text):
    """Calibration from the .txt that JEOL and Hitachi instruments write next to each image."""
    m = re.search(r"^\s*PixelSize\s*=\s*([\d.]+)", text, re.MULTILINE)
    if m:  # Hitachi SU series: nanometres per pixel
        return float(m.group(1)) * 1e-3, "metadata:Hitachi .txt", {"PixelSize_nm": float(m.group(1))}
    bar = re.search(r"\$\$SM_MICRON_BAR\s+([\d.]+)", text)
    marker = re.search(r"\$\$SM_MICRON_MARKER\s+([\d.]+)\s*(nm|um|µm|mm)", text, re.IGNORECASE)
    if bar and marker:  # JEOL: bar length in px and the length it represents
        um = _parse_number(marker.group(1)) * _unit_factor(marker.group(2))
        return um / float(bar.group(1)), "metadata:JEOL .txt", {"bar_px": float(bar.group(1)), "marker": marker.group(0)}
    mag = re.search(r"^\s*Magnification\s*=\s*([\d.]+)", text, re.MULTILINE)
    size = re.search(r"^\s*DataSize\s*=\s*(\d+)\s*x\s*(\d+)", text, re.MULTILINE)
    if mag and size and float(mag.group(1)) > 0:  # Hitachi S series (e.g. S-4700)
        width = int(size.group(1))
        um = HITACHI_REFERENCE_WIDTH_UM / float(mag.group(1)) / width
        details = {"magnification": float(mag.group(1)), "data_width_px": width}
        inst = re.search(r"^\s*InstructName\s*=\s*(\S+)", text, re.MULTILINE)
        marker_nm = re.search(r"^\s*MicronMarker\s*=\s*([\d.]+)", text, re.MULTILINE)
        if inst:
            details["instrument"] = inst.group(1)
        if marker_nm:
            details["marker_um"] = float(marker_nm.group(1)) / 1000
        return um, "metadata:Hitachi .txt (magnification)", details
    return None


def _from_sidecar(path):
    if path is None:
        return None
    for candidate in (Path(path).with_suffix(".txt"), Path(path).with_suffix(".TXT")):
        if candidate.exists():
            return parse_sidecar_text(candidate.read_text(errors="ignore"))
    return None


_PHENOM_PIXEL = re.compile(rb'<pixelWidth unit="(\w+)">([\d.eE+-]+)</pixelWidth>')
_PHENOM_BAR = re.compile(rb"<databarHeight>(\d+)</databarHeight>")
_PHENOM_EDITION = re.compile(rb"<edition>([^<]{1,60})</edition>")


def _from_phenom_xml(data):
    """Thermo Fisher Phenom desktop SEMs embed an XML block in JPG and TIFF files."""
    if not data or b"<FeiImage" not in data:
        return None
    m = _PHENOM_PIXEL.search(data)
    if not m:
        return None
    factor = _unit_factor(m.group(1).decode())
    if not factor:
        return None
    details = {}
    bar = _PHENOM_BAR.search(data)
    if bar:
        details["databar_height"] = int(bar.group(1))
    edition = _PHENOM_EDITION.search(data)
    if edition:
        details["instrument"] = edition.group(1).decode(errors="ignore")
    return float(m.group(2)) * factor, "metadata:Phenom XML", details


def calibration_from_metadata(path=None, data=None, sidecar_text=None):
    """Return (um_per_px, source, details) from embedded or sidecar metadata, or None."""
    sidecar = parse_sidecar_text(sidecar_text) if sidecar_text else _from_sidecar(path)
    if sidecar:
        return sidecar
    if data is None and path is not None:
        try:
            data = Path(path).read_bytes()
        except OSError:
            data = None
    phenom = _from_phenom_xml(data)
    if phenom and 0 < phenom[0] <= _MAX_PLAUSIBLE_UM_PER_PX:
        return phenom
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


def find_strip_bars(image, databar_top):
    """Scale bars inside the information strip, thresholded against the strip's own background.

    Strips draw the bar in grey as well as white, so a whole-image brightness cut can miss it.
    """
    h, w = image.shape
    if databar_top >= h - 6:
        return []
    strip = image[databar_top:]
    if strip.max() - strip.min() < 0.1:
        return []
    t = filters.threshold_otsu(strip)
    binary = strip > t if strip.mean() < t else strip < t
    found = find_scale_bar_candidates(strip, binaries=[("strip", binary)])
    for c in found:
        x0, y0, x1, y1 = c["bbox"]
        c["bbox"] = (x0, y0 + databar_top, x1, y1 + databar_top)
    return found


def find_scale_bar_candidates(image, search_top=0, binaries=None):
    """Long, thin, solid, isolated horizontal bars. Returns dicts sorted best-first."""
    h, w = image.shape
    min_len = max(20, int(0.025 * w))
    max_thick = max(3, int(0.03 * h)) if binaries is None else max(3, int(0.25 * h))
    candidates = []
    if binaries is None:
        binaries = (("bright", image >= 0.8 * image.max()), ("dark", image <= 0.15))
    for polarity, binary in binaries:
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


def find_tick_ruler(image, databar_top):
    """Hitachi-style scale: a row of evenly spaced short ticks in the information strip.

    Returns a bar-like dict whose length is the distance between the first and last tick.
    """
    h, w = image.shape
    if databar_top >= h - 8:
        return None
    strip = image[databar_top:]
    bright_text = strip.mean() < 0.5
    binary = (strip >= 0.6 * strip.max()) if bright_text else (strip <= 0.4 * strip.max())
    n, _, stats, cents = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    ticks = [(stats[i], cents[i]) for i in range(1, n)
             if stats[i][2] <= 6 and stats[i][3] >= 4 and stats[i][3] >= 2 * stats[i][2]
             and stats[i][3] <= 0.5 * strip.shape[0]]
    rows = {}
    for st, c in ticks:
        rows.setdefault((round(st[1] / 3), round(st[3] / 3)), []).append((c[0], st))
    best = None
    for group in rows.values():
        if len(group) < 5:
            continue
        group.sort(key=lambda g: g[0])
        xs = np.array([g[0] for g in group])
        gaps = np.diff(xs)
        if gaps.mean() <= 3 or gaps.std() / gaps.mean() > 0.1:
            continue
        if best is None or len(group) > len(best):
            best = group
    if best is None:
        return None
    x0, x1 = best[0][0], best[-1][0]
    y0 = min(g[1][1] for g in best) + databar_top
    y1 = max(g[1][1] + g[1][3] for g in best) + databar_top
    return {"bbox": (int(round(x0)), int(y0), int(round(x1)) + 1, int(y1)), "length_px": float(x1 - x0),
            "polarity": "bright" if bright_text else "dark", "score": 0.0, "kind": "tick ruler",
            "ticks": len(best)}


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


# Scale bars carry one significant digit (Phenom: 3, 8, 20, 70 µm...; Hitachi: 0.5, 2, 30 µm...),
# sometimes 1.5 or 2.5. Field widths printed beside them (47.2 µm, 94.8 µm) do not.
_ROUND_MANTISSAS = (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9)


def _is_round_value(value):
    if value <= 0:
        return False
    mantissa = value / 10 ** math.floor(math.log10(value))
    return any(abs(mantissa - m) < 1e-6 for m in _ROUND_MANTISSAS)


def _significant_digits(number_text):
    """"47.2" -> 3, "120" -> 2, "0.50" -> 1: bar labels have at most two, field widths three."""
    digits = number_text.replace(",", ".").replace(".", "").lstrip("0")
    return len(digits.rstrip("0")) or 1


_TOKEN_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(nm|mm|[µμuyp]{1,2}\s?m)$", re.IGNORECASE)


def _ocr_tokens(region, scale, psm):
    """Words with positions (in region pixels) from one OCR pass."""
    import os

    import pytesseract
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # tesseract's own threading is slower for small crops
    u8 = (region * 255).astype(np.uint8)
    up = u8 if scale == 1 else cv2.resize(u8, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:
        bw = 255 - bw  # tesseract wants dark text on a light page
    pad = 20
    bw = cv2.copyMakeBorder(bw, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    try:
        d = pytesseract.image_to_data(bw, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    words = []
    for i, text in enumerate(d["text"]):
        text = text.strip()
        if not text:
            continue
        x, y = (d["left"][i] - pad) / scale, (d["top"][i] - pad) / scale
        words.append((text, x, y, d["width"][i] / scale, d["height"][i] / scale))
    return words


_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_UNIT_RE = re.compile(r"^(nm|mm|[µμuyp]{1,2}m)$", re.IGNORECASE)


def _label_candidates(words):
    """Number+unit tokens: "40µm" as one word, or a number with a unit word just to its right."""
    out = []
    for t, x, y, w, h in words:
        m = _TOKEN_RE.match(t.replace(",", "."))
        if m and _parse_number(m.group(1)) > 0:
            out.append((_parse_number(m.group(1)) * _unit_factor(m.group(2)), t, (x, y, x + w, y + h)))
            continue
        if not _NUMBER_RE.match(t) or _parse_number(t) <= 0:
            continue
        best = None
        for t2, x2, y2, w2, h2 in words:
            overlap = min(y + h, y2 + h2) - max(y, y2)
            gap = x2 - (x + w)
            if _UNIT_RE.match(t2) and overlap > 0.4 * min(h, h2) and -2 <= gap < 1.5 * max(h, h2):
                if best is None or gap < best[0]:
                    best = (gap, t2, (x, min(y, y2), x2 + w2, max(y + h, y2 + h2)))
        if best:
            out.append((_parse_number(t) * _unit_factor(best[1]), f"{t} {best[1]}", best[2]))
    return out


def _nearest_round(value):
    """Closest round scale-bar value (one significant digit, or 1.5 / 2.5)."""
    exp = math.floor(math.log10(value))
    options = [m * 10 ** e for e in (exp - 1, exp, exp + 1) for m in _ROUND_MANTISSAS]
    return min(options, key=lambda o: abs(math.log(o / value)))


def read_bar_label(image, bbox, databar_top=None):
    """OCR the scale-bar label and return (length_um, raw_text) or (None, raw_text).

    Every number-with-unit near the bar is read; the one closest to the bar wins, so other
    information-strip fields (field width, working distance) are not mistaken for it. Reading at
    two magnifications and voting guards against single-digit misreads (5 vs 2, 8 vs 3).
    """
    h, w = image.shape
    x0, y0, x1, y1 = bbox
    bar_len = x1 - x0
    text_h = max(14, int(0.035 * h), 3 * (y1 - y0))
    rx0, rx1 = max(0, int(x0 - 0.6 * bar_len)), min(w, int(x1 + 0.6 * bar_len))
    ry0, ry1 = max(0, y0 - 3 * text_h), min(h, y1 + 3 * text_h)
    if databar_top is not None and y0 >= databar_top:
        ry0 = max(ry0, databar_top)  # the label is in the information strip, not in the micrograph
    region = image[ry0:ry1, rx0:rx1]
    if region.size == 0:
        return None, ""
    # Tesseract reads best with ~30 px tall text; strip text is roughly a third of the strip height.
    strip_h = (h - databar_top) if databar_top is not None and y0 >= databar_top else 3 * text_h
    base = int(np.clip(round(30 / max(strip_h / 3, 1)), 1, 4))
    votes, seen = {}, []
    for scale, psm in ((base, 11), (base + 1, 11), (base, 6), (base + 2, 11)):
        words = _ocr_tokens(region, scale, psm)
        seen.extend(t for t, *_ in words)
        best = None
        for value, text, (bx0, by0, bx1, by1) in _label_candidates(words):
            bx0, bx1, by0, by1 = bx0 + rx0, bx1 + rx0, by0 + ry0, by1 + ry0
            dx = max(bx0 - x1, x0 - bx1, 0)
            dy = max(by0 - y1, y0 - by1, 0)
            dist = math.hypot(dx, dy)
            # Bars carry round values; a non-round number nearby is usually the field width.
            rank = dist + (0 if _significant_digits(re.match(r"[\d.,]+", text).group(0)) <= 2 else 1e6)
            if best is None or rank < best[0]:
                best = (rank, value, text)
        if best is not None:
            key = round(best[1], 6)
            count, dist, text = votes.get(key, (0, best[0], best[2]))
            votes[key] = (count + 1, min(dist, best[0]), text)
            if count + 1 >= 2 and len(votes) == 1:
                return best[1], text  # two independent readings agree: done
    if not votes:
        return None, " ".join(dict.fromkeys(seen))[:200]
    value, (count, dist, text) = max(votes.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
    return value, text


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


def calibrate(image, path=None, data=None, manual_um_per_px=None, manual_bar_um=None, use_ocr=True,
              sidecar_text=None):
    """Work out µm/px. Priority: user override, metadata, scale bar or tick ruler (+OCR), HFW text."""
    meta = None
    if path is not None or data is not None or sidecar_text:
        meta = calibration_from_metadata(path, data, sidecar_text)
    h = image.shape[0]
    if meta and meta[2].get("databar_height"):
        databar_top = max(0, h - int(meta[2]["databar_height"]))
    else:
        databar_top = find_databar_top(image)

    # Prefer a bar in the information strip, then a tick ruler there, then a bar drawn in the image.
    in_strip = find_strip_bars(image, databar_top) if databar_top < h else []
    bars = in_strip or ([r] if databar_top < h and (r := find_tick_ruler(image, databar_top)) else [])
    if not bars:
        bars = find_scale_bar_candidates(image)
    bar = bars[0] if bars else None
    details = {"databar_top": databar_top, "bar_candidates": len(bars)}
    if bar is not None and bar.get("kind"):
        details["scale_kind"] = bar["kind"]

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

    bar_um, label = None, None
    can_ocr = use_ocr and ocr_available()
    if bar and can_ocr:
        bar_um, label = read_bar_label(image, bar["bbox"], databar_top)
        if bar_um and bar_um / bar["length_px"] > _MAX_PLAUSIBLE_UM_PER_PX:
            label = f"{label} (rejected: implies {bar_um / bar['length_px']:.3g} µm/px)"
            bar_um = None
        elif bar_um and _significant_digits(re.match(r"[\d.,]+", label).group(0)) >= 3:
            # A three-digit number beside the bar is usually the field width printed in the strip.
            # If treating it as one makes the bar a round length, the reading is self-consistent.
            implied = bar["length_px"] * bar_um / image.shape[1]
            nice = _nearest_round(implied)
            if abs(implied - nice) / nice < 0.03:
                details["field_width_um"] = bar_um
                label = f"{nice:g} um (bar implied by field width {label})"
                bar_um = nice
            else:
                details["warning"] = (f"The scale bar label was read as '{label}', which is not a usual "
                                      "scale-bar value. Please check it in the Scale calibration tab.")
    if bar and not bar_um and meta and meta[2].get("marker_um"):
        bar_um, label = meta[2]["marker_um"], f"{meta[2]['marker_um']:g} um (from metadata)"

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
        cal = _cal(bar_um / bar["length_px"], "scale_bar" if not bar.get("kind") else bar["kind"], bar_um=bar_um)
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
