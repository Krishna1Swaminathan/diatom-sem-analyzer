"""Image in, measurements out."""

from pathlib import Path

from .calibration import calibrate
from .classification import extract_features
from .config import AnalysisConfig
from .damage import grade_damage
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


def analyze_image(source, name=None, config=None, manual_um_per_px=None, manual_bar_um=None,
                  library=None, databar_top=None, use_ocr=True, sidecar_text=None):
    """Run the full pipeline on one image (a path, or raw bytes plus ``name``)."""
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
    frustules = measure_frustules(labels, region.shape, exclude_boxes=exclude)

    for fr in frustules:
        fr.pores, fr.crack_candidates = detect_pores(region, labels, fr, um, config.pores)
        fr.features = extract_features(fr, region, labels, um)
        identify_and_grade(fr, library, config)
        if config.segmentation.method == "round_cells":
            fr.damage = "not graded"  # outlines are fitted circles, so outline-based grading is meaningless

    if not frustules:
        warnings.append("No frustules were detected. Try lowering the minimum frustule size.")
    return ImageResult(name=name, image=image, analysis_height=top, calibration=cal, labels=labels,
                       frustules=frustules, warnings=warnings)
