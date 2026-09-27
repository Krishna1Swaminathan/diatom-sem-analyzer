"""Image in, measurements out."""

from pathlib import Path

from skimage.segmentation import relabel_sequential

from .calibration import calibrate
from .classification import extract_features
from .config import AnalysisConfig
from .damage import grade_damage
from .editing import apply_edits, label_at
from .loading import load_image
from .measurements import classify_morphotype, classify_view, measure_frustules
from .models import ImageResult
from .pores import detect_pores
from .segmentation import segment_frustules

FRAGMENT_GROUPS = ("pores", "texture")


def _inset_exclusion(cal, analysis_height, width):
    """Box around a scale bar drawn inside the image, including its text label."""
    if not cal.scale_bar_bbox:
        return []
    x0, y0, x1, y1 = cal.scale_bar_bbox
    if y0 >= analysis_height:
        return []
    bar_len = x1 - x0
    text_h = max(3 * (y1 - y0), int(0.06 * analysis_height))
    return [(max(0, x0 - bar_len // 6), max(0, y0 - text_h), min(width, x1 + bar_len // 6),
             min(analysis_height, y1 + text_h // 2))]


def identify_and_grade(fr, library, config):
    """Species match, damage grade, view and morphotype for one measured frustule."""
    fr.species, fr.species_confidence, fr.species_distance = "", 0.0, float("nan")
    has_library = library is not None and len(library) > 0
    cls = config.classifier
    reference = None
    if has_library:
        fr.species, fr.species_confidence, fr.species_distance = library.classify(
            fr.features, k=cls.k, unknown_distance=cls.unknown_distance)
        if fr.species != "unknown" and fr.species_distance <= 1.5:
            reference = library.reference(fr.species)
    fr.damage = grade_damage(fr, fr.crack_candidates, config.damage, reference)
    if fr.damage == "fragmented" and has_library:
        # A broken outline says nothing about the species; the pore pattern still does.
        fr.species, fr.species_confidence, fr.species_distance = library.classify(
            fr.features, k=cls.k, unknown_distance=cls.unknown_distance, groups=FRAGMENT_GROUPS)
    fr.view = classify_view(fr, config.view)
    fr.morphotype = classify_morphotype(fr, config.view)


GRADES = ("intact", "cracked", "fragmented")


def _apply_grades(frustules, labels, edits, config):
    by_id = {fr.frustule_id: fr for fr in frustules}
    for op, x1, y1, _x2, _y2, value in edits:
        if op != "grade" or value not in GRADES:
            continue
        fr = by_id.get(label_at(labels, x1, y1))
        if fr is not None:
            fr.damage, fr.graded_by = value, "you"
            fr.morphotype = classify_morphotype(fr, config.view)


def analyze_image(source, name=None, config=None, manual_um_per_px=None, manual_bar_um=None,
                  library=None, databar_top=None, use_ocr=True, sidecar_text=None, edits=()):
    """Run the full pipeline on one image (a path, or raw bytes plus ``name``).

    ``edits`` are manual corrections, ``(op, x1, y1, x2, y2, value)``, replayed in order: "add" and
    "remove" change the outlines before anything is measured, "grade" sets the condition of the
    frustule at (x1, y1) to ``value`` ("intact", "cracked" or "fragmented") afterwards.
    """
    config = config or AnalysisConfig()
    is_path = isinstance(source, (str, Path))
    name = name or (Path(source).name if is_path else "image")
    image = load_image(source, name=name)

    cal = calibrate(image, path=source if is_path else None, data=None if is_path else bytes(source),
                    manual_um_per_px=manual_um_per_px, manual_bar_um=manual_bar_um, use_ocr=use_ocr,
                    sidecar_text=sidecar_text)
    top = int(databar_top) if databar_top else int(cal.details.get("databar_top", image.shape[0]))
    region = image[:top]
    um = cal.um_per_px if cal.ok else None

    warnings = []
    if not cal.ok:
        warnings.append(f"No physical scale ({cal.details.get('reason', 'unknown')}). Sizes are reported "
                        "in pixels only; enter the scale bar value or µm/pixel to get µm.")
    if "warning" in cal.details:
        warnings.append(cal.details["warning"])

    exclude = _inset_exclusion(cal, top, image.shape[1])
    labels = segment_frustules(region, um, config.segmentation, exclude_boxes=exclude)
    manual = set()
    if edits:
        labels, manual = apply_edits(region, labels, edits)
        labels, forward, _ = relabel_sequential(labels)
        manual = {int(forward[m]) for m in manual}
    frustules = measure_frustules(labels, region.shape, exclude_boxes=exclude)

    for fr in frustules:
        fr.pores, fr.crack_candidates = detect_pores(region, labels, fr, um, config.pores)
        fr.features = extract_features(fr, region, labels, um)
        identify_and_grade(fr, library, config)
        fr.origin = "manual" if fr.frustule_id in manual else "auto"
        if config.segmentation.method == "round_cells" and fr.origin == "auto":
            fr.damage = "not graded"  # outlines are fitted circles, so outline-based grading is meaningless
        elif fr.origin == "manual":
            fr.damage = "not graded"  # a traced outline is approximate; its kinks would read as breaks
    _apply_grades(frustules, labels, edits, config)

    if not frustules:
        warnings.append("No frustules were detected. Try lowering the minimum frustule size.")
    return ImageResult(name=name, image=image, analysis_height=top, calibration=cal, labels=labels,
                       frustules=frustules, warnings=warnings)
