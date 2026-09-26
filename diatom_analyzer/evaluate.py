"""Test the pipeline against images with known answers, and build species libraries from datasets.

    python -m diatom_analyzer.evaluate synthetic --frames 30          # full benchmark, known truth
    python -m diatom_analyzer.evaluate voc path/to/kaggle_diatoms     # detection + species (VOC XML)
    python -m diatom_analyzer.evaluate folders path/to/species_dirs   # few-shot species accuracy
    python -m diatom_analyzer.evaluate build-library path --format folders --out species_library

Each command prints a Markdown report and writes it (plus JSON) to --out-report.
"""

import argparse
import io
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from .classification import SpeciesLibrary
from .config import AnalysisConfig
from .datasets import box_iou, frustule_box, greedy_match, load_species_folders, load_voc
from .pipeline import analyze_image, identify_and_grade
from .synthetic import SPECIES_PRESETS, random_frame, specimen_crop

DAMAGE = ["intact", "cracked", "fragmented", "uncertain"]


# --------------------------------------------------------------------------- helpers


def _png(img):
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f} %"


def _mean(values):
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.mean(values)) if values else float("nan")


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if p + r else float("nan")
    return p, r, f


def mask_iou_matrix(gt, det):
    n_g, n_d = int(gt.max()), int(det.max())
    idx = gt.astype(np.int64) * (n_d + 1) + det.astype(np.int64)
    inter = np.bincount(idx.ravel(), minlength=(n_g + 1) * (n_d + 1)).reshape(n_g + 1, n_d + 1)
    area_g, area_d = inter.sum(1), inter.sum(0)
    union = area_g[:, None] + area_d[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        iou = np.where(union > 0, inter / union, 0.0)
    return iou[1:, 1:]


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _species_block(pairs, title):
    """pairs: list of (true, predicted). Returns markdown + stats."""
    if not pairs:
        return f"### {title}\n\nNo test specimens.\n", {}
    correct = sum(t == p for t, p in pairs)
    per = defaultdict(lambda: [0, 0])
    for t, p in pairs:
        per[t][1] += 1
        per[t][0] += t == p
    rows = [(s, f"{c}/{n}", _pct(c / n)) for s, (c, n) in sorted(per.items())]
    confusions = Counter((t, p) for t, p in pairs if t != p).most_common(6)
    md = [f"### {title}", "", f"Accuracy: **{_pct(correct / len(pairs))}** ({correct}/{len(pairs)})", "",
          _table(["species", "correct", "accuracy"], rows)]
    if confusions:
        md += ["", "Most common mistakes: " + "; ".join(f"{t} → {p} ({n})" for (t, p), n in confusions)]
    return "\n".join(md) + "\n", {"accuracy": correct / len(pairs), "n": len(pairs),
                                  "per_species": {s: c / n for s, (c, n) in per.items()}}


def _write_report(md, data, out):
    print(md)
    if out:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(md)
        (out / "report.json").write_text(json.dumps(data, indent=1, default=float))
        print(f"\nReport written to {out}/report.md", file=sys.stderr)


# --------------------------------------------------------------------------- synthetic benchmark


def _expected_shape_class(gt):
    return "centric" if gt["kind"] in ("centric", "triangular") else "pennate"


def build_synthetic_library(k, config, seed=0):
    lib = SpeciesLibrary("/nonexistent-species-library")
    for s_idx, species in enumerate(SPECIES_PRESETS):
        for j in range(k):
            img, _ = specimen_crop(species, seed=seed + 7919 * s_idx + 104729 + j)
            res = analyze_image(_png(img), name="exemplar.png", manual_um_per_px=0.05, config=config)
            if res.frustules:
                lib.add_features(species, max(res.frustules, key=lambda f: f.area_px).features)
    return lib


def run_synthetic(frames=30, seed=0, crowded=False, shots=(1, 3, 5), out=None, use_ocr=True):
    config = AnalysisConfig()
    matched, frame_rows = [], []
    tp = fp = fn = 0
    cal_ok = 0
    count_err, times = [], []
    for s in range(seed, seed + frames):
        img, truth, gt_labels = random_frame(s, crowded=crowded)
        t0 = time.time()
        res = analyze_image(_png(img), name=f"synthetic_{s}.png", config=config, use_ocr=use_ocr)
        times.append(time.time() - t0)
        um_true = truth["um_per_px"]
        good_cal = res.calibration.ok and abs(res.calibration.um_per_px - um_true) / um_true < 0.01
        cal_ok += good_cal
        gts = [g for g in truth["frustules"] if g["visible_fraction"] > 0.2]
        iou = mask_iou_matrix(gt_labels, res.labels[: gt_labels.shape[0]])
        pairs = [(i, j) for i, j, _ in greedy_match(iou, 0.5) if truth["frustules"][i]["visible_fraction"] > 0.2]
        tp += len(pairs)
        fp += len(res.frustules) - len(pairs)
        fn += len(gts) - len(pairs)
        count_err.append(abs(len(res.frustules) - len(gts)))
        by_label = {f.frustule_id: f for f in res.frustules}
        for i, j in pairs:
            matched.append((truth["frustules"][i], by_label[j + 1], um_true))
        frame_rows.append((s, len(gts), len(res.frustules), len(pairs), res.calibration.source,
                           "ok" if good_cal else "WRONG", f"{times[-1]:.1f}"))

    p, r, f1 = _prf(tp, fp, fn)
    data = {"frames": frames, "crowded": crowded, "detection": {"precision": p, "recall": r, "f1": f1,
                                                                 "mean_abs_count_error": _mean(count_err)},
            "calibration_correct": cal_ok / frames, "seconds_per_frame": _mean(times)}

    # Damage (no species library).
    confusion = Counter((g["damage"], fr.damage) for g, fr, _ in matched)
    damage_acc = sum(n for (t, pr), n in confusion.items() if t == pr) / max(1, len(matched))
    by_kind = defaultdict(lambda: [0, 0])
    for g, fr, _ in matched:
        key = g["species"] or g["kind"]
        by_kind[key][1] += 1
        by_kind[key][0] += g["damage"] == fr.damage

    # Geometry and pores.
    len_err, wid_err, ori_err, shape_ok, shape_n = [], [], [], 0, 0
    pore_count_err, pore_bias = [], []
    for g, fr, um in matched:
        whole = g["damage"] != "fragmented" and g["visible_fraction"] > 0.99
        if whole and "mask_length_um" in g:
            len_err.append(abs(fr.length_px * um - g["mask_length_um"]) / g["mask_length_um"])
            wid_err.append(abs(fr.width_px * um - g["mask_width_um"]) / g["mask_width_um"])
        if whole and g["kind"] in ("pennate", "girdle") and fr.orientation_deg is not None \
                and g["mask_length_um"] / g["mask_width_um"] >= 1.5:
            ori_err.append(abs((fr.orientation_deg - g["angle_deg"] % 180 + 90) % 180 - 90))
        if whole and g["kind"] != "girdle":
            shape_n += 1
            predicted = "centric" if fr.morphotype == "centric" else "pennate"
            shape_ok += predicted == _expected_shape_class(g)
        if g["damage"] == "intact" and g["visible_fraction"] > 0.99 and g["pores"]:
            pore_count_err.append(abs(len(fr.pores) - len(g["pores"])) / len(g["pores"]))
            if fr.pores:
                pore_bias.append(np.median([pp.diameter_px for pp in fr.pores]) * um - g["pore_diameter_um"])

    data.update(damage_accuracy=damage_acc, length_error=_mean(len_err), width_error=_mean(wid_err),
                orientation_error_deg=_mean(ori_err), centric_vs_pennate=shape_ok / max(1, shape_n),
                pore_count_error=_mean(pore_count_err), pore_diameter_bias_um=_mean(pore_bias))

    md = [f"# Synthetic benchmark ({frames} frames{', crowded' if crowded else ''})", "",
          "Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; "
          "the scale is read from the image's own scale bar.", "",
          "## Detection, scale, measurements", "",
          _table(["measure", "result"], [
              ("Frustules (truth / detected / matched IoU≥0.5)", f"{tp + fn} / {tp + fp} / {tp}"),
              ("Precision / recall / F1", f"{_pct(p)} / {_pct(r)} / {_pct(f1)}"),
              ("Mean count error per image", f"{_mean(count_err):.2f}"),
              ("Scale correct (±1 %)", f"{cal_ok}/{frames}"),
              ("Length error (mean / 90th pct)", f"{_pct(_mean(len_err))} / "
                                                  f"{_pct(float(np.percentile(len_err, 90)) if len_err else None)}"),
              ("Width error (mean)", _pct(_mean(wid_err))),
              ("Orientation error (mean / max)", f"{_mean(ori_err):.2f}° / {max(ori_err, default=float('nan')):.2f}°"),
              ("Centric vs pennate correct", _pct(shape_ok / max(1, shape_n))),
              ("Pore count error (mean)", _pct(_mean(pore_count_err))),
              ("Pore diameter bias (mean)", f"{1000 * _mean(pore_bias):+.0f} nm"),
              ("Time per image", f"{_mean(times):.1f} s"),
          ]), "",
          "## Damage grading (no species library)", "",
          f"Accuracy: **{_pct(damage_acc)}**", "",
          _table(["truth \\ predicted"] + DAMAGE,
                 [[t] + [confusion.get((t, pr), 0) for pr in DAMAGE] for t in DAMAGE[:3]]), "",
          _table(["species", "damage correct"], [(k, f"{c}/{n}") for k, (c, n) in sorted(by_kind.items())]), ""]

    # Few-shot species identification: library built from k single-specimen images per species.
    data["species"] = {}
    for k in shots:
        lib = build_synthetic_library(k, config, seed=seed)
        pairs_all, pairs_intact, dmg_ok = [], [], 0
        for g, fr, _ in matched:
            identify_and_grade(fr, lib, config)
            pairs_all.append((g["species"], fr.species))
            if g["damage"] == "intact":
                pairs_intact.append((g["species"], fr.species))
            dmg_ok += g["damage"] == fr.damage
        block, stats = _species_block(pairs_all, f"Species, {k} example(s) per species (all frustules)")
        intact_acc = sum(t == p for t, p in pairs_intact) / max(1, len(pairs_intact))
        stats.update(intact_accuracy=intact_acc, damage_accuracy_with_library=dmg_ok / max(1, len(matched)))
        data["species"][k] = stats
        md += [block, f"Intact frustules only: {_pct(intact_acc)}. Damage accuracy with this library "
                      f"(species-relative outline tests): {_pct(dmg_ok / max(1, len(matched)))}.", ""]

    # Open set: a species missing from the library should come back "unknown", not misnamed.
    k = max(shots)
    full = build_synthetic_library(k, config, seed=seed)
    unseen_total = unseen_unknown = 0
    for held in SPECIES_PRESETS:
        lib = SpeciesLibrary("/nonexistent-species-library")
        for sp, fe, _ in full.exemplars:
            if sp != held:
                lib.add_features(sp, fe)
        for g, fr, _ in matched:
            if g["species"] == held and g["damage"] == "intact":
                identify_and_grade(fr, lib, config)
                unseen_total += 1
                unseen_unknown += fr.species == "unknown"
    data["unseen_species_reported_unknown"] = unseen_unknown / max(1, unseen_total)
    md += ["### Species missing from the library", "",
           f"Leaving each species out of a {k}-example library in turn, "
           f"**{_pct(unseen_unknown / max(1, unseen_total))}** of its intact specimens were reported as "
           f"*unknown* ({unseen_unknown}/{unseen_total}); the rest were given the closest look-alike's name.", ""]
    for _, fr, _ in matched:
        identify_and_grade(fr, None, config)

    md += ["## Per image", "", _table(["seed", "truth", "detected", "matched", "scale source", "scale", "s"],
                                      frame_rows)]
    _write_report("\n".join(md), data, out)
    return data


# --------------------------------------------------------------------------- real datasets


def _analyze_path(path, um_per_px, config):
    try:
        return analyze_image(path, config=config, manual_um_per_px=um_per_px)
    except Exception as exc:  # corrupt or unsupported file: skip, but say so
        print(f"[skip] {path}: {exc}", file=sys.stderr)
        return None


def run_voc(root, um_per_px=None, train_fraction=0.5, shots=5, max_images=300, seed=0, out=None):
    config = AnalysisConfig()
    items = load_voc(root)
    if not items:
        sys.exit(f"No Pascal VOC annotations (*.xml with <object>/<bndbox>) found under {root}")
    random.Random(seed).shuffle(items)
    items = items[:max_images]
    n_train = int(len(items) * train_fraction)
    tp = fp = fn = 0
    count_err = []
    train_feats, test_pairs = defaultdict(list), []
    for idx, item in enumerate(items):
        res = _analyze_path(item.path, um_per_px, config)
        if res is None:
            continue
        dets = res.frustules
        iou = [[box_iou(b.box, frustule_box(fr)) for fr in dets] for b in item.boxes]
        pairs = greedy_match(iou, 0.5)
        tp += len(pairs)
        fp += len(dets) - len(pairs)
        fn += len(item.boxes) - len(pairs)
        count_err.append(abs(len(dets) - len(item.boxes)))
        for i, j, _ in pairs:
            entry = (item.boxes[i].species, dets[j])
            if idx < n_train:
                train_feats[entry[0]].append(entry[1].features)
            else:
                test_pairs.append(entry)
        print(f"[{idx + 1}/{len(items)}] {item.path.name}: {len(item.boxes)} labelled, {len(dets)} detected, "
              f"{len(pairs)} matched", file=sys.stderr)

    p, r, f1 = _prf(tp, fp, fn)
    lib = SpeciesLibrary("/nonexistent-species-library")
    rng = random.Random(seed)
    for species, feats in train_feats.items():
        rng.shuffle(feats)
        for fe in feats[:shots]:
            lib.add_features(species, fe)
    pairs = []
    for species, fr in test_pairs:
        if species in lib.species:
            identify_and_grade(fr, lib, config)
            pairs.append((species, fr.species))
    block, stats = _species_block(pairs, f"Species, up to {shots} training example(s) per species")
    md = [f"# Pascal VOC evaluation: {root}", "", f"{len(items)} images ({n_train} train / "
          f"{len(items) - n_train} test for species).", "",
          _table(["measure", "result"], [
              ("Labelled / detected / matched (box IoU≥0.5)", f"{tp + fn} / {tp + fp} / {tp}"),
              ("Precision / recall / F1", f"{_pct(p)} / {_pct(r)} / {_pct(f1)}"),
              ("Mean count error per image", f"{_mean(count_err):.2f}"),
              ("Species in the library", str(len(lib.species))),
          ]), "", block]
    data = {"images": len(items), "detection": {"precision": p, "recall": r, "f1": f1,
                                                "mean_abs_count_error": _mean(count_err)}, "species": stats}
    _write_report("\n".join(md), data, out)
    return data


def _largest_features(path, um_per_px, config):
    res = _analyze_path(path, um_per_px, config)
    if res is None or not res.frustules:
        return None
    return max(res.frustules, key=lambda f: f.area_px)


def run_folders(root, shots=5, max_test=20, um_per_px=None, seed=0, out=None):
    config = AnalysisConfig()
    classes = load_species_folders(root)
    classes = {s: f for s, f in classes.items() if len(f) > shots}
    if not classes:
        sys.exit(f"Need species folders with more than {shots} images under {root}")
    rng = random.Random(seed)
    lib = SpeciesLibrary("/nonexistent-species-library")
    tests, missed = [], 0
    for species, files in classes.items():
        files = list(files)
        rng.shuffle(files)
        for path in files[:shots]:
            fr = _largest_features(path, um_per_px, config)
            if fr is not None:
                lib.add_features(species, fr.features)
        for path in files[shots:shots + max_test]:
            fr = _largest_features(path, um_per_px, config)
            if fr is None:
                missed += 1
            else:
                tests.append((species, fr))
        print(f"{species}: done", file=sys.stderr)
    pairs = []
    for species, fr in tests:
        identify_and_grade(fr, lib, config)
        pairs.append((species, fr.species))
    block, stats = _species_block(pairs, f"Species, {shots} training example(s) per species")
    md = [f"# Folder-per-species evaluation: {root}", "", f"{len(classes)} species; "
          f"{len(pairs)} test images; {missed} test images with no diatom detected.", "", block]
    _write_report("\n".join(md), {"species": stats, "no_detection": missed}, out)
    return stats


def build_library(root, fmt, out, shots=10, um_per_px=None, seed=0):
    """Copy up to ``shots`` analysed examples per species into a library folder the app can use."""
    config = AnalysisConfig()
    lib = SpeciesLibrary(out)
    rng = random.Random(seed)
    added = Counter()
    if fmt == "folders":
        for species, files in load_species_folders(root).items():
            files = list(files)
            rng.shuffle(files)
            for path in files:
                if added[species] >= shots:
                    break
                res = _analyze_path(path, um_per_px, config)
                if res and res.frustules:
                    fr = max(res.frustules, key=lambda f: f.area_px)
                    lib.add(species, fr, res.image, path.name, res.calibration.um_per_px)
                    added[species] += 1
    else:
        items = load_voc(root)
        rng.shuffle(items)
        for item in items:
            if all(added[b.species] >= shots for b in item.boxes):
                continue
            res = _analyze_path(item.path, um_per_px, config)
            if res is None:
                continue
            iou = [[box_iou(b.box, frustule_box(fr)) for fr in res.frustules] for b in item.boxes]
            for i, j, _ in greedy_match(iou, 0.5):
                species = item.boxes[i].species
                if added[species] < shots:
                    lib.add(species, res.frustules[j], res.image, item.path.name, res.calibration.um_per_px)
                    added[species] += 1
    print(f"Library {out}: " + ", ".join(f"{s} ({n})" for s, n in sorted(added.items())))
    return added


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m diatom_analyzer.evaluate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synthetic", help="benchmark on generated images with exact ground truth")
    s.add_argument("--frames", type=int, default=30)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--crowded", action="store_true", help="let frustules touch and overlap")
    s.add_argument("--shots", type=int, nargs="+", default=[1, 3, 5])
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--out-report", default="reports/synthetic")

    v = sub.add_parser("voc", help="dataset with Pascal VOC XML boxes (e.g. Kaggle Diatom Dataset)")
    v.add_argument("root")
    v.add_argument("--um-per-px", type=float)
    v.add_argument("--train-fraction", type=float, default=0.5)
    v.add_argument("--shots", type=int, default=5)
    v.add_argument("--max-images", type=int, default=300)
    v.add_argument("--seed", type=int, default=0)
    v.add_argument("--out-report", default="reports/voc")

    f = sub.add_parser("folders", help="one sub-folder of images per species (e.g. ADIAC, UDE)")
    f.add_argument("root")
    f.add_argument("--shots", type=int, default=5)
    f.add_argument("--max-test", type=int, default=20)
    f.add_argument("--um-per-px", type=float)
    f.add_argument("--seed", type=int, default=0)
    f.add_argument("--out-report", default="reports/folders")

    b = sub.add_parser("build-library", help="fill a species library folder from a labelled dataset")
    b.add_argument("root")
    b.add_argument("--format", choices=["folders", "voc"], required=True)
    b.add_argument("--out", default="species_library")
    b.add_argument("--shots", type=int, default=10)
    b.add_argument("--um-per-px", type=float)
    b.add_argument("--seed", type=int, default=0)

    a = parser.parse_args(argv)
    if a.cmd == "synthetic":
        run_synthetic(a.frames, a.seed, a.crowded, tuple(a.shots), a.out_report, use_ocr=not a.no_ocr)
    elif a.cmd == "voc":
        run_voc(a.root, a.um_per_px, a.train_fraction, a.shots, a.max_images, a.seed, a.out_report)
    elif a.cmd == "folders":
        run_folders(a.root, a.shots, a.max_test, a.um_per_px, a.seed, a.out_report)
    else:
        build_library(a.root, a.format, a.out, a.shots, a.um_per_px, a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
