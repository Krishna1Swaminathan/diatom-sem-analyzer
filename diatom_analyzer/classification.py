"""Species identification by comparison with a user-built reference library (few-shot).

The library is a folder with one sub-folder per species:

    species_library/
        Cyclotella meneghiniana/
            ex_20260926_1200_3.json   <- features saved from the app ("teach" button)
            ex_20260926_1200_3.png    <- preview crop
            my_reference_photo.tif    <- any image dropped in by hand; features computed on load

No training step is needed: a new frustule is compared with every exemplar using
rotation-invariant descriptors (outline, size, pore pattern, surface texture), each scaled by
a typical within-species variation, so a distance of 1 means "one typical deviation away".
With one example per species the variation comes from built-in priors; as more examples are
added, each species' own spread is learned from them (shrunk toward the prior).
"""

import json
import math
import re
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree
from skimage.feature import local_binary_pattern

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

# Prior within-species variation of each feature. Diatoms shrink with every division, and
# their proportions change as they do, so size and aspect ratio get generous priors.
FEATURE_GROUPS = {
    "shape": {"log_aspect": 0.25, "solidity": 0.03, "rect_fill": 0.05, "ellipse_iou": 0.05, "circularity": 0.06},
    "size": {"log_length_um": 0.35, "log_width_um": 0.25},
    "pores": {"log_pore_d_um": 0.2, "log_pore_density": 0.3, "porosity": 0.05, "log_pore_nn_um": 0.15},
    "texture": {f"lbp_{i}": 0.03 for i in range(10)},
    "contour": {f"fd_{k}": 0.03 for k in range(2, 7)},
}


def _fourier_descriptors(mask):
    contours, _ = cv2.findContours(np.pad(mask.astype(np.uint8), 1), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return {f"fd_{k}": float("nan") for k in range(2, 7)}
    pts = max(contours, key=cv2.contourArea)[:, 0, :].astype(float)
    seg = np.hypot(*np.diff(np.vstack([pts, pts[:1]]), axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    closed = np.vstack([pts, pts[:1]])
    t = np.linspace(0, s[-1], 128, endpoint=False)
    x, y = np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])
    r = np.hypot(x - x.mean(), y - y.mean())
    spectrum = np.abs(np.fft.rfft(r))
    base = spectrum[0] or 1.0
    return {f"fd_{k}": float(spectrum[k] / base) for k in range(2, 7)}


def _lbp_hist(crop, mask, radius):
    u8 = np.clip(crop * 255, 0, 255).astype(np.uint8)
    codes = local_binary_pattern(u8, P=8, R=radius, method="uniform")
    vals = codes[mask]
    if vals.size == 0:
        return {f"lbp_{i}": float("nan") for i in range(10)}
    hist = np.bincount(vals.astype(int), minlength=10)[:10] / vals.size
    return {f"lbp_{i}": float(v) for i, v in enumerate(hist)}


def extract_features(fr, image, labels, um_per_px):
    r0, c0, r1, c1 = fr.bbox
    crop = image[r0:r1, c0:c1]
    mask = labels[r0:r1, c0:c1] == fr.frustule_id
    nan = float("nan")
    feats = {
        "log_aspect": math.log(max(fr.aspect_ratio, 1.0)),
        "solidity": fr.solidity,
        "rect_fill": fr.rect_fill,
        "ellipse_iou": fr.ellipse_iou,
        "circularity": fr.circularity,
        "porosity": sum(p.area_px for p in fr.pores) / fr.area_px if fr.area_px else nan,
    }
    cal = bool(um_per_px)
    feats["log_length_um"] = math.log(fr.length_px * um_per_px) if cal else nan
    feats["log_width_um"] = math.log(fr.width_px * um_per_px) if cal else nan
    if fr.pores and cal:
        d = np.median([p.diameter_px for p in fr.pores]) * um_per_px
        feats["log_pore_d_um"] = math.log(d)
        feats["log_pore_density"] = math.log1p(len(fr.pores) / (fr.area_px * um_per_px**2))
    else:
        feats["log_pore_d_um"] = nan
        feats["log_pore_density"] = math.log1p(0.0) if cal else nan
    if len(fr.pores) >= 3 and cal:
        pts = np.array([[p.x_px, p.y_px] for p in fr.pores])
        dist, _ = cKDTree(pts).query(pts, k=2)
        feats["log_pore_nn_um"] = math.log(np.median(dist[:, 1]) * um_per_px)
    else:
        feats["log_pore_nn_um"] = nan
    radius = int(np.clip(round(0.25 / um_per_px), 1, 6)) if cal else 2
    feats.update(_lbp_hist(crop, mask, radius))
    feats.update(_fourier_descriptors(mask))
    return feats


PRIOR_WEIGHT = 3  # the prior counts as this many examples when learning a species' spread


def feature_distance(a, b, groups=None, scales=None):
    """Scaled distance between two feature dicts, ignoring features missing on either side.

    ``scales`` optionally overrides the prior spread of individual features.
    """
    group_sq = []
    for group, priors in FEATURE_GROUPS.items():
        if groups and group not in groups:
            continue
        terms = []
        for name, prior in priors.items():
            va, vb = a.get(name), b.get(name)
            if va is None or vb is None or not (np.isfinite(va) and np.isfinite(vb)):
                continue
            scale = scales.get(name, prior) if scales else prior
            terms.append(((va - vb) / scale) ** 2)
        if terms:
            group_sq.append(float(np.mean(terms)))
    return math.sqrt(np.mean(group_sq)) if group_sq else float("inf")


def _safe_name(name):
    return re.sub(r"[^\w\- .()]", "_", name).strip() or "unnamed"


class SpeciesLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.exemplars = []  # (species, features, path)
        self.reload()

    def reload(self):
        self.exemplars = []
        self._scales = None
        if not self.root.exists():
            return
        for species_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            species = species_dir.name
            covered = set()
            for js in sorted(species_dir.glob("*.json")):
                try:
                    data = json.loads(js.read_text())
                    self.exemplars.append((species, data["features"], js))
                    covered.add(data.get("preview", ""))
                except (ValueError, KeyError):
                    continue
            for img in sorted(species_dir.iterdir()):
                if img.suffix.lower() in IMAGE_SUFFIXES and img.name not in covered:
                    feats = self._features_from_image(img)
                    if feats:
                        self.exemplars.append((species, feats, img))

    def _features_from_image(self, path):
        """Hand-added reference image: analyse it and cache the largest frustule's features."""
        from .pipeline import analyze_image

        cache = path.with_suffix(path.suffix + ".features.json")
        if cache.exists():
            try:
                return json.loads(cache.read_text())["features"]
            except (ValueError, KeyError):
                pass
        try:
            result = analyze_image(path, library=None)
        except Exception:
            return None
        if not result.frustules:
            return None
        biggest = max(result.frustules, key=lambda f: f.area_px)
        cache.write_text(json.dumps({"features": biggest.features, "source": path.name}, default=float))
        return biggest.features

    @property
    def species(self):
        return sorted({s for s, _, _ in self.exemplars})

    def __len__(self):
        return len(self.exemplars)

    def add_features(self, species, features):
        """In-memory exemplar (not written to disk), e.g. for benchmarking."""
        self.exemplars.append((species, features, None))
        self._scales = None

    def species_scales(self, species):
        """Per-feature spread of one species: the prior, updated by its examples' own variance."""
        if getattr(self, "_scales", None) is None:
            self._scales = {}
        if species not in self._scales:
            rows = [f for s, f, _ in self.exemplars if s == species]
            learned = {}
            for priors in FEATURE_GROUPS.values():
                for name, prior in priors.items():
                    vals = np.array([r.get(name, np.nan) for r in rows], dtype=float)
                    vals = vals[np.isfinite(vals)]
                    n = len(vals)
                    if n >= 2:
                        var = float(np.var(vals, ddof=1))
                        learned[name] = math.sqrt((PRIOR_WEIGHT * prior**2 + (n - 1) * var)
                                                  / (PRIOR_WEIGHT + n - 1))
            self._scales[species] = learned
        return self._scales[species]

    def add(self, species, fr, image, source_name, um_per_px):
        folder = self.root / _safe_name(species)
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"ex_{time.strftime('%Y%m%d_%H%M%S')}_{fr.frustule_id}_{uuid.uuid4().hex[:6]}"
        r0, c0, r1, c1 = fr.bbox
        crop = np.clip(image[r0:r1, c0:c1] * 255, 0, 255).astype(np.uint8)
        cv2.imwrite(str(folder / f"{stem}.png"), crop)
        payload = {"features": fr.features, "preview": f"{stem}.png", "source_image": source_name,
                   "frustule_id": fr.frustule_id, "um_per_px": um_per_px}
        (folder / f"{stem}.json").write_text(json.dumps(payload, indent=1, default=float))
        self.exemplars.append((folder.name, fr.features, folder / f"{stem}.json"))
        self._scales = None

    def reference(self, species):
        """Mean feature values of a species' exemplars (its typical outline)."""
        rows = [f for s, f, _ in self.exemplars if s == species]
        if not rows:
            return None
        out = {}
        for key in ("solidity", "rect_fill", "ellipse_iou"):
            vals = [r[key] for r in rows if r.get(key) is not None and np.isfinite(r[key])]
            if vals:
                out[key] = float(np.mean(vals))
        return out

    def classify(self, features, k=3, unknown_distance=1.5, groups=None):
        """Return (species, confidence 0-1, distance). ``groups`` restricts the features compared."""
        if not self.exemplars:
            return "", 0.0, float("inf")
        per_species = {}
        for species, ex, _ in self.exemplars:
            per_species.setdefault(species, []).append(
                feature_distance(features, ex, groups, self.species_scales(species)))
        class_d = {s: float(np.mean(sorted(d)[:k])) for s, d in per_species.items()}
        best = min(class_d, key=class_d.get)
        d_best = class_d[best]
        if not np.isfinite(d_best):
            return "unknown", 0.0, d_best
        logits = np.array([-(d**2) / 2 for d in class_d.values()])
        rel = float(np.exp(-(d_best**2) / 2 - logits.max()) / np.exp(logits - logits.max()).sum())
        in_dist = math.exp(-(d_best**2) / (2 * (unknown_distance / 2) ** 2))
        confidence = rel * in_dist
        if d_best > unknown_distance:
            return "unknown", confidence, d_best
        return best, confidence, d_best
