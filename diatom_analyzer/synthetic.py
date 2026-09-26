"""Synthetic SEM-style diatom images with known ground truth, for testing, benchmarking and demos.

Real SEM images with hand-made answers are scarce, so this module renders frustules whose every
property is known: outline, size, orientation, damage, species and each pore's position and size.
"""

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
    kind: str  # "centric", "pennate", "girdle" or "triangular"
    cx_um: float
    cy_um: float
    length_um: float  # pennate: apical length along the (possibly curved) axis; triangle: tip-to-tip span
    width_um: float
    angle_deg: float = 0.0
    damage: str = "intact"  # "intact", "cracked" or "fragmented"
    pore_diameter_um: float = 0.5
    pore_spacing_um: float = 1.1
    profile: str = "elliptic"  # pennate outline: "elliptic", "lanceolate" (pointed) or "linear"
    curvature: float = 0.0  # pennate axis curvature, 1/µm (crescent-shaped when > 0)
    species: str = ""


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

# Look-alike "species": each has a characteristic outline, size range and pore pattern, with
# within-species variation (diatoms shrink over generations, so size varies most).
SPECIES_PRESETS = {
    "Cyclotella-like": dict(kind="centric", length=(6, 11), pore_d=0.35, spacing=0.8),
    "Coscinodiscus-like": dict(kind="centric", length=(14, 20), pore_d=0.9, spacing=1.6),
    "Navicula-like": dict(kind="pennate", profile="lanceolate", length=(16, 26), width=(5.0, 6.5),
                          pore_d=0.3, spacing=0.7),
    "Pinnularia-like": dict(kind="pennate", profile="linear", length=(24, 34), width=(5.0, 6.5),
                            pore_d=0.6, spacing=1.3),
    "Synedra-like": dict(kind="pennate", profile="linear", length=(30, 42), width=(2.6, 3.4),
                         pore_d=0.25, spacing=0.6),
    "Cymbella-like": dict(kind="pennate", profile="lanceolate", curvature=(0.035, 0.05), length=(18, 26),
                          width=(5.0, 6.5), pore_d=0.35, spacing=0.8),
    "Triceratium-like": dict(kind="triangular", length=(12, 18), pore_d=0.7, spacing=1.3),
}


def _font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


# --------------------------------------------------------------------------- geometry


def _to_local(xs, ys, spec, um_per_px):
    """Pixel coords -> (along, across) in the frustule's own straight axis frame, in px."""
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    t = math.radians(spec.angle_deg)
    dx, dy = xs - cx, ys - cy
    along = dx * math.cos(t) - dy * math.sin(t)
    across = dx * math.sin(t) + dy * math.cos(t)
    return along, across


def _from_local(along, across, spec, um_per_px):
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    t = math.radians(spec.angle_deg)
    x = cx + along * np.cos(t) + across * np.sin(t)
    y = cy - along * np.sin(t) + across * np.cos(t)
    return x, y


def _profile(t, profile):
    """Relative half-width of a pennate valve at relative position t in [-1, 1] along its axis."""
    t = np.clip(np.abs(t), 0, 1)
    if profile == "lanceolate":
        return 1 - t**2  # pointed apices
    if profile == "linear":
        return np.sqrt(np.clip(1 - t**8, 0, 1))  # parallel sides, rounded ends
    return np.sqrt(np.clip(1 - t**2, 0, 1))


def _bend(u, v, spec, um_per_px):
    """Map straight-frame (u, v) onto a curved axis (crescent shapes), centred on the spec."""
    k = spec.curvature * um_per_px  # per px
    if k <= 0:
        return u, v
    r = 1.0 / k
    phi = u / r
    x = (r - v) * np.sin(phi)
    y = r - (r - v) * np.cos(phi)
    half_l = spec.length_um / um_per_px / 2
    y_mid = r - r * math.cos(half_l / r)
    return x, y - y_mid / 2


def _outline_mask(shape, spec, um_per_px):
    mask = np.zeros(shape, np.uint8)
    cx, cy = spec.cx_um / um_per_px, spec.cy_um / um_per_px
    half_l, half_w = spec.length_um / um_per_px / 2, spec.width_um / um_per_px / 2
    if spec.kind == "girdle":
        box = cv2.boxPoints(((cx, cy), (2 * half_l, 2 * half_w), -spec.angle_deg))
        cv2.fillPoly(mask, [np.round(box).astype(np.int32)], 1)
    elif spec.kind == "triangular":
        corner = 0.14 * half_l
        rv = half_l - corner
        base = math.radians(spec.angle_deg + 90)
        angles = [base + k * 2 * math.pi / 3 for k in range(3)]
        tri = np.array([[cx + rv * math.cos(a), cy - rv * math.sin(a)] for a in angles])
        cv2.fillPoly(mask, [np.round(tri).astype(np.int32)], 1)
        size = 2 * int(round(corner)) + 1
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    elif spec.kind == "pennate" and (spec.profile != "elliptic" or spec.curvature > 0):
        u = np.linspace(-half_l, half_l, 400)
        w = half_w * _profile(u / half_l, spec.profile)
        uu = np.concatenate([u, u[::-1]])
        vv = np.concatenate([w, -w[::-1]])
        bu, bv = _bend(uu, vv, spec, um_per_px)
        x, y = _from_local(bu, bv, spec, um_per_px)
        cv2.fillPoly(mask, [np.round(np.stack([x, y], -1)).astype(np.int32)], 1)
    else:
        cv2.ellipse(mask, ((cx, cy), (2 * half_l, 2 * half_w), -spec.angle_deg), 1, -1)
    return mask.astype(bool)


def _apply_fragmentation(mask, spec, um_per_px, rng):
    """Break the frustule: pennates lose one end along a jagged line, others lose a wedge."""
    ys, xs = np.nonzero(mask)
    along, across = _to_local(xs.astype(float), ys.astype(float), spec, um_per_px)
    half_l = spec.length_um / um_per_px / 2
    if spec.kind == "pennate":
        jag = 0.08 * half_l * np.sin(across / 6.0) + 0.05 * half_l * np.sign(np.sin(across / 2.5))
        keep = along < rng.uniform(0.0, 0.3) * half_l + jag
    else:
        angle = np.degrees(np.arctan2(across, along))
        start = rng.uniform(-180, 180)
        keep = ((angle - start) % 360) > rng.uniform(90, 140)
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
    elif spec.kind == "triangular":  # hexagonal areolae
        row_h = spacing * math.sqrt(3) / 2
        j = -int(half_l / row_h) - 1
        while j * row_h <= half_l:
            off = (j % 2) * spacing / 2
            i = -int(half_l / spacing) - 1
            while i * spacing <= half_l:
                pts.append((i * spacing + off, j * row_h))
                i += 1
            j += 1
    elif spec.kind == "pennate":
        u = -half_l
        us, vs = [], []
        while u <= half_l:
            v = spacing * 0.9
            while v <= half_w:
                us += [u, u]
                vs += [v, -v]
                v += spacing * 0.8
            u += spacing
        bu, bv = _bend(np.array(us), np.array(vs), spec, um_per_px)
        return list(zip(*_from_local(bu, bv, spec, um_per_px)))
    else:  # girdle view: rows of pores along a few bands
        for band in (-0.55, -0.2, 0.2, 0.55):
            u = -half_l + spacing
            while u <= half_l - spacing:
                pts.append((u, band * half_w))
                u += spacing
    return [_from_local(a, c, spec, um_per_px) for a, c in pts]


def _draw_crack(canvas, spec, um_per_px, rng):
    half_l = min(spec.length_um, 2.5 * spec.width_um) / um_per_px / 2
    n = 12
    along = np.linspace(-0.75 * half_l, 0.65 * half_l, n)
    across = np.cumsum(rng.normal(0, 0.05 * half_l, n))
    across -= across.mean()
    rot = math.radians(rng.uniform(25, 65) if spec.kind != "pennate" else rng.uniform(60, 90))
    ra = along * math.cos(rot) - across * math.sin(rot)
    rc = along * math.sin(rot) + across * math.cos(rot)
    x, y = _from_local(ra, rc, spec, um_per_px)
    pts = np.round(np.stack([x, y], -1)).astype(np.int32)
    width = max(2, int(round(0.12 / um_per_px)))
    cv2.polylines(canvas, [pts], False, 0.08, thickness=width, lineType=cv2.LINE_AA)
    return float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))


def _mask_geometry(mask, um_per_px):
    ys, xs = np.nonzero(mask)
    if xs.size < 5:
        return {}
    pts = np.stack([xs, ys], -1).astype(np.float32)
    (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
    return {"mask_length_um": (max(rw, rh) + 1) * um_per_px, "mask_width_um": (min(rw, rh) + 1) * um_per_px,
            "mask_centroid_px": [float(xs.mean()), float(ys.mean())],
            "mask_bbox": [int(ys.min()), int(xs.min()), int(ys.max()) + 1, int(xs.max()) + 1]}


# --------------------------------------------------------------------------- rendering


def render_scene(specs, field_um=DEMO_FIELD_UM, um_per_px=0.05, seed=0, noise=0.03,
                 databar=True, scale_bar_um=10, bar_style="databar", return_labels=False):
    """Render a synthetic SEM frame.

    Returns (uint8 image, truth dict), plus the ground-truth label image when ``return_labels``.
    ``bar_style`` is "databar" (black info strip under the image), "inset" (white bar drawn
    inside the image) or "none". Later specs are drawn on top of earlier ones.
    """
    rng = np.random.default_rng(seed)
    w = int(round(field_um[0] / um_per_px))
    h = int(round(field_um[1] / um_per_px))

    yy, xx = np.mgrid[0:h, 0:w]
    gx, gy = rng.uniform(0.02, 0.08), rng.uniform(0.0, 0.06)
    canvas = 0.22 + gx * (xx / w) + gy * (yy / h)
    canvas += 0.03 * cv2.GaussianBlur(rng.normal(0, 1, (h, w)), (0, 0), 12)
    labels = np.zeros((h, w), np.int32)

    truth = {"um_per_px": um_per_px, "frustules": []}
    for idx, spec in enumerate(specs):
        mask = _outline_mask((h, w), spec, um_per_px)
        if spec.damage == "fragmented":
            mask = _apply_fragmentation(mask, spec, um_per_px, rng)
        inner = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
        shell = 0.62 + 0.25 * np.exp(-inner / 4.0)
        canvas[mask] = shell[mask]
        labels[mask] = idx + 1

        pore_r = spec.pore_diameter_um / um_per_px / 2
        pores = []
        for x, y in _pore_centres(spec, um_per_px):
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < w and 0 <= yi < h) or inner[yi, xi] < pore_r + 2:
                continue
            cv2.ellipse(canvas, ((float(x), float(y)), (2 * pore_r, 2 * pore_r), 0), 0.12, -1,
                        lineType=cv2.LINE_AA)
            pores.append({"x_px": float(x), "y_px": float(y), "diameter_um": spec.pore_diameter_um})

        crack_len = 0.0
        if spec.damage == "cracked":
            crack_len = _draw_crack(canvas, spec, um_per_px, rng)

        entry = asdict(spec)
        entry.update(id=idx + 1, area_px=int(mask.sum()), pores=pores, crack_length_px=crack_len,
                     **_mask_geometry(mask, um_per_px))
        truth["frustules"].append(entry)

    # Occlusion: a frustule partly covered by a later one keeps only its visible pixels.
    for entry in truth["frustules"]:
        visible = labels == entry["id"]
        entry["visible_fraction"] = float(visible.sum() / max(entry["area_px"], 1))
        entry["touches_border"] = bool(visible[0].any() or visible[-1].any() or visible[:, 0].any()
                                       or visible[:, -1].any())

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
    if return_labels:
        return img, truth, labels
    return img, truth


def sample_specimen(species, rng, cx_um=0.0, cy_um=0.0, angle_deg=None, damage="intact"):
    """One frustule of a preset species, with natural within-species variation."""
    p = SPECIES_PRESETS[species]
    length = rng.uniform(*p["length"])
    width = rng.uniform(*p["width"]) if "width" in p else length
    return FrustuleSpec(
        kind=p["kind"], cx_um=cx_um, cy_um=cy_um, length_um=length, width_um=width,
        angle_deg=rng.uniform(0, 180) if angle_deg is None else angle_deg, damage=damage,
        pore_diameter_um=p["pore_d"] * rng.uniform(0.94, 1.06),
        pore_spacing_um=p["spacing"] * rng.uniform(0.95, 1.05),
        profile=p.get("profile", "elliptic"),
        curvature=rng.uniform(*p["curvature"]) if "curvature" in p else 0.0,
        species=species)


def _nice_bar(field_width_um):
    target = 0.25 * field_width_um
    options = [m * 10**e for e in range(-2, 4) for m in (1, 2, 5)]
    return min(options, key=lambda v: abs(math.log(v / target)))


def random_scene(seed, species=None, n=(3, 7), field_um=DEMO_FIELD_UM, damage_p=(0.7, 0.15, 0.15),
                 crowded=False):
    """Random specs placed in the field. ``crowded`` lets frustules touch and overlap slightly."""
    rng = np.random.default_rng(seed)
    pool = list(species or SPECIES_PRESETS)
    target = int(rng.integers(n[0], n[1] + 1))
    # Place the biggest first so large species get a fair chance at the free space.
    wanted = []
    for _ in range(target):
        damage = str(rng.choice(["intact", "cracked", "fragmented"], p=damage_p))
        wanted.append(sample_specimen(str(rng.choice(pool)), rng, damage=damage))
    wanted.sort(key=lambda s: -s.length_um * s.width_um)
    grid_um = 0.25  # collision checks on a coarse occupancy grid of the real outlines
    gh, gw = int(field_um[1] / grid_um), int(field_um[0] / grid_um)
    occupied = np.zeros((gh, gw), bool)
    gap = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))  # ~0.6 µm clearance
    specs = []
    for spec in wanted:
        for _ in range(150):
            spec.angle_deg = rng.uniform(0, 180)
            spec.cx_um = rng.uniform(0, field_um[0])
            spec.cy_um = rng.uniform(0, field_um[1])
            footprint = _outline_mask((gh, gw), spec, grid_um)
            full = footprint.sum()
            if full == 0 or footprint[0].any() or footprint[-1].any() or footprint[:, 0].any() \
                    or footprint[:, -1].any():
                continue  # must lie wholly inside the frame
            overlap = (footprint & occupied).sum() / full
            if overlap <= (0.08 if crowded else 0.0):
                specs.append(spec)
                occupied |= cv2.dilate(footprint.astype(np.uint8), gap).astype(bool) if not crowded else footprint
                break
    order = rng.permutation(len(specs))
    return [specs[i] for i in order]


def random_frame(seed, species=None, crowded=False, bar_style="databar"):
    """A random scene rendered with random magnification and noise. Returns (img, truth, labels)."""
    rng = np.random.default_rng(seed + 10_000)
    um_per_px = float(rng.choice([0.035, 0.05, 0.07]))
    field = DEMO_FIELD_UM
    specs = random_scene(seed, species=species, crowded=crowded, field_um=field)
    return render_scene(specs, field_um=field, um_per_px=um_per_px, seed=seed, noise=rng.uniform(0.02, 0.05),
                        scale_bar_um=_nice_bar(field[0]), bar_style=bar_style, return_labels=True)


def specimen_crop(species, seed, um_per_px=0.05):
    """A single intact frustule of ``species`` centred in its own small frame (for exemplars)."""
    rng = np.random.default_rng(seed)
    spec = sample_specimen(species, rng)
    side = spec.length_um + 4.0
    spec.cx_um = spec.cy_um = side / 2
    img, truth = render_scene([spec], field_um=(side, side), um_per_px=um_per_px, seed=seed, bar_style="none")
    return img, truth


# --------------------------------------------------------------------------- scale bars


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
    mixed, _, _ = random_frame(7)
    Image.fromarray(mixed).save(args.outdir / "synthetic_mixed_species.png")
    print(f"wrote demo images to {args.outdir}")
