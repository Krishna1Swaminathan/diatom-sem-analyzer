"""Synthetic SEM-style diatom images with known ground truth, for testing and demos."""

import math
from dataclasses import asdict, dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@dataclass
class FrustuleSpec:
    kind: str  # "centric", "pennate" or "girdle"
    cx_um: float
    cy_um: float
    length_um: float
    width_um: float
    angle_deg: float = 0.0
    damage: str = "intact"  # "intact", "cracked" or "fragmented"
    pore_diameter_um: float = 0.5
    pore_spacing_um: float = 1.1


DEMO_FIELD_UM = (51.2, 38.4)

DEMO_SCENE = [
    FrustuleSpec("centric", 8.5, 8.5, 12, 12),
    FrustuleSpec("centric", 23.0, 8.5, 10, 10, damage="cracked", pore_diameter_um=0.45, pore_spacing_um=1.0),
    FrustuleSpec("pennate", 39.0, 9.5, 22, 6, angle_deg=30, pore_diameter_um=0.35, pore_spacing_um=0.8),
    FrustuleSpec("girdle", 10.0, 27.0, 14, 7, angle_deg=-15, pore_diameter_um=0.3, pore_spacing_um=0.9),
    FrustuleSpec("pennate", 25.5, 27.5, 18, 5, angle_deg=80, damage="fragmented", pore_diameter_um=0.35,
                 pore_spacing_um=0.8),
    FrustuleSpec("centric", 38.5, 28.5, 7, 7, pore_diameter_um=0.4, pore_spacing_um=0.9),
    FrustuleSpec("centric", 44.9, 30.3, 7, 7, pore_diameter_um=0.4, pore_spacing_um=0.9),
]


def _font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _outline_mask(shape, spec, um_per_px):
    mask = np.zeros(shape, np.uint8)
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    half_l, half_w = spec.length_um / um_per_px / 2, spec.width_um / um_per_px / 2
    if spec.kind == "girdle":
        box = cv2.boxPoints(((cx, cy), (2 * half_l, 2 * half_w), -spec.angle_deg))
        cv2.fillPoly(mask, [np.round(box).astype(np.int32)], 1)
    else:
        cv2.ellipse(mask, ((cx, cy), (2 * half_l, 2 * half_w), -spec.angle_deg), 1, -1)
    return mask.astype(bool)


def _to_local(xs, ys, spec, um_per_px):
    """Pixel coords -> (along, across) in the frustule's own axis frame, in px."""
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    t = math.radians(spec.angle_deg)
    dx, dy = xs - cx, ys - cy
    along = dx * math.cos(t) - dy * math.sin(t)
    across = dx * math.sin(t) + dy * math.cos(t)
    return along, across


def _from_local(along, across, spec, um_per_px):
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    t = math.radians(spec.angle_deg)
    x = cx + along * math.cos(t) + across * math.sin(t)
    y = cy - along * math.sin(t) + across * math.cos(t)
    return x, y


def _apply_fragmentation(mask, spec, um_per_px, rng):
    """Break the frustule: pennates lose one end along a jagged line, others lose a wedge."""
    ys, xs = np.nonzero(mask)
    along, across = _to_local(xs.astype(float), ys.astype(float), spec, um_per_px)
    half_l = spec.length_um / um_per_px / 2
    if spec.kind == "pennate":
        jag = 0.08 * half_l * np.sin(across / 6.0) + 0.05 * half_l * np.sign(np.sin(across / 2.5))
        keep = along < 0.15 * half_l + jag
    else:
        angle = np.degrees(np.arctan2(across, along))
        start = rng.uniform(-180, 180)
        keep = ((angle - start) % 360) > 110
    out = np.zeros_like(mask)
    out[ys[keep], xs[keep]] = True
    return out


def _pore_centres(spec, um_per_px):
    spacing = spec.pore_spacing_um / um_per_px
    half_l = spec.length_um / um_per_px / 2
    half_w = spec.width_um / um_per_px / 2
    pts = []
    if spec.kind == "centric":
        r = spacing * 0.9
        pts.append((0.0, 0.0))
        while r < half_l:
            n = max(6, int(2 * math.pi * r / spacing))
            offset = (len(pts) % 2) * math.pi / n
            for i in range(n):
                a = 2 * math.pi * i / n + offset
                pts.append((r * math.cos(a), r * math.sin(a)))
            r += spacing
    elif spec.kind == "pennate":
        u = -half_l
        while u <= half_l:
            v = spacing * 0.9
            while v <= half_w:
                pts.append((u, v))
                pts.append((u, -v))
                v += spacing * 0.8
            u += spacing
    else:  # girdle view: rows of pores along a few bands
        for band in (-0.55, -0.2, 0.2, 0.55):
            u = -half_l + spacing
            while u <= half_l - spacing:
                pts.append((u, band * half_w))
                u += spacing
    return [_from_local(a, c, spec, um_per_px) for a, c in pts]


def _draw_crack(canvas, spec, um_per_px, rng):
    half_l = spec.length_um / um_per_px / 2
    n = 12
    along = np.linspace(-0.75 * half_l, 0.65 * half_l, n)
    across = np.cumsum(rng.normal(0, 0.05 * half_l, n))
    across -= across.mean()
    rot = math.radians(35)
    pts = []
    for a, c in zip(along, across):
        ra = a * math.cos(rot) - c * math.sin(rot)
        rc = a * math.sin(rot) + c * math.cos(rot)
        pts.append(_from_local(ra, rc, spec, um_per_px))
    pts = np.round(np.array(pts)).astype(np.int32)
    width = max(2, int(round(0.12 / um_per_px)))
    cv2.polylines(canvas, [pts], False, 0.08, thickness=width, lineType=cv2.LINE_AA)
    length = float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))
    return length


def render_scene(specs, field_um=DEMO_FIELD_UM, um_per_px=0.05, seed=0, noise=0.03,
                 databar=True, scale_bar_um=10, bar_style="databar"):
    """Render a synthetic SEM frame.

    Returns (uint8 image, truth dict). ``bar_style`` is "databar" (black info strip under the
    image), "inset" (white bar drawn inside the image) or "none".
    """
    rng = np.random.default_rng(seed)
    w = int(round(field_um[0] / um_per_px))
    h = int(round(field_um[1] / um_per_px))

    yy, xx = np.mgrid[0:h, 0:w]
    canvas = 0.22 + 0.06 * (xx / w) + 0.04 * (yy / h)
    canvas += 0.03 * cv2.GaussianBlur(rng.normal(0, 1, (h, w)), (0, 0), 12)

    truth = {"um_per_px": um_per_px, "frustules": []}
    for idx, spec in enumerate(specs):
        mask = _outline_mask((h, w), spec, um_per_px)
        if spec.damage == "fragmented":
            mask = _apply_fragmentation(mask, spec, um_per_px, rng)
        inner = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
        shell = 0.62 + 0.25 * np.exp(-inner / 4.0)
        canvas[mask] = shell[mask]

        pore_r = spec.pore_diameter_um / um_per_px / 2
        pores = []
        for x, y in _pore_centres(spec, um_per_px):
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < w and 0 <= yi < h) or inner[yi, xi] < pore_r + 2:
                continue
            cv2.circle(canvas, (xi, yi), 0, 0.0, -1)
            cv2.ellipse(canvas, ((x, y), (2 * pore_r, 2 * pore_r), 0), 0.12, -1, lineType=cv2.LINE_AA)
            pores.append({"x_px": x, "y_px": y, "diameter_um": spec.pore_diameter_um})

        crack_len = 0.0
        if spec.damage == "cracked":
            crack_len = _draw_crack(canvas, spec, um_per_px, rng)

        entry = asdict(spec)
        entry.update(id=idx, area_px=int(mask.sum()), pores=pores, crack_length_px=crack_len)
        truth["frustules"].append(entry)

    canvas = cv2.GaussianBlur(canvas, (0, 0), 1.0)
    canvas += rng.normal(0, noise, canvas.shape)
    img = np.clip(canvas * 255, 0, 255).astype(np.uint8)

    truth["analysis_height"] = h
    if bar_style == "databar" and databar:
        img = _add_databar(img, um_per_px, scale_bar_um)
    elif bar_style == "inset":
        img = _add_inset_bar(img, um_per_px, scale_bar_um)
    truth["scale_bar_um"] = scale_bar_um
    truth["scale_bar_px"] = scale_bar_um / um_per_px
    return img, truth


def _unit_label(value_um):
    if value_um < 1:
        return f"{value_um * 1000:g} nm"
    return f"{value_um:g} µm"


def _add_databar(img, um_per_px, scale_bar_um):
    h, w = img.shape
    bar_h = max(60, h // 10)
    full = np.zeros((h + bar_h, w), np.uint8)
    full[:h] = img
    pil = Image.fromarray(full)
    draw = ImageDraw.Draw(pil)
    font = _font(max(14, bar_h // 3))
    draw.line([(0, h), (w, h)], fill=255, width=2)
    bar_len = scale_bar_um / um_per_px
    info = "HV 5.00 kV   WD 9.8 mm   Det SE"
    info_font = font
    while draw.textlength(info, font=info_font) > w - bar_len - 80 and info_font.size > 8:
        info_font = _font(info_font.size - 1)
    draw.text((12, h + bar_h * 0.3), info, fill=255, font=info_font)
    x1 = w - 30
    x0 = x1 - bar_len
    y_bar = h + int(bar_h * 0.72)
    draw.rectangle([x0, y_bar, x1 - 1, y_bar + max(4, bar_h // 12)], fill=255)
    label = _unit_label(scale_bar_um)
    tw = draw.textlength(label, font=font)
    draw.text(((x0 + x1) / 2 - tw / 2, h + bar_h * 0.18), label, fill=255, font=font)
    return np.array(pil)


def _add_inset_bar(img, um_per_px, scale_bar_um):
    h, w = img.shape
    pil = Image.fromarray(img)
    draw = ImageDraw.Draw(pil)
    font = _font(max(14, h // 28))
    bar_len = scale_bar_um / um_per_px
    x1 = w - 40
    x0 = x1 - bar_len
    y = h - 40
    draw.rectangle([x0, y, x1 - 1, y + max(4, h // 150)], fill=255)
    label = _unit_label(scale_bar_um)
    tw = draw.textlength(label, font=font)
    draw.text(((x0 + x1) / 2 - tw / 2, y - font.size - 10), label, fill=255, font=font)
    return np.array(pil)


def save_tiff_imagej(path, img, um_per_px):
    import tifffile
    tifffile.imwrite(path, img, imagej=True, resolution=(1 / um_per_px, 1 / um_per_px),
                     metadata={"unit": "micron"})


def save_tiff_fei(path, img, um_per_px):
    """Write a TIFF carrying an FEI/Thermo-style metadata block (tag 34682)."""
    import tifffile
    ini = f"[User]\nDate=01/01/2026\n[Scan]\nPixelWidth={um_per_px * 1e-6:.6e}\nPixelHeight={um_per_px * 1e-6:.6e}\n"
    tifffile.imwrite(path, img, extratags=[(34682, "s", 0, ini, True)])


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate synthetic SEM demo images.")
    parser.add_argument("outdir", type=Path)
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    image, gt = render_scene(DEMO_SCENE)
    Image.fromarray(image).save(args.outdir / "synthetic_databar.png")
    save_tiff_fei(args.outdir / "synthetic_fei_metadata.tif", image[: gt["analysis_height"]], gt["um_per_px"])
    inset, _ = render_scene(DEMO_SCENE, bar_style="inset", seed=1)
    Image.fromarray(inset).save(args.outdir / "synthetic_inset_bar.png")
    (args.outdir / "synthetic_truth.json").write_text(json.dumps(gt, indent=1, default=float))
    print(f"wrote demo images to {args.outdir}")
