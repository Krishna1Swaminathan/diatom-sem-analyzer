"""Spreadsheet export: one workbook, one row per frustule and one row per pore."""

import math
import time
from collections import Counter

import pandas as pd

from . import __version__

COLUMN_GUIDE = [
    ("Frustules", "image", "Source file name"),
    ("Frustules", "frustule_id", "Number shown on the annotated image"),
    ("Frustules", "origin", "auto = found by the detector, manual = added by clicking on it in the app"),
    ("Frustules", "species", "Best match in the species library ('unknown' = no confident match, blank = no library)"),
    ("Frustules", "species_confidence", "0-1; how clearly the best species beats the others and how close it is"),
    ("Frustules", "morphotype", "centric / pennate (elliptic) / pennate (linear) / girdle view / fragment"),
    ("Frustules", "view", "valve = seen face-on, girdle = seen from the side (rectangular outline)"),
    ("Frustules", "damage", "intact / cracked / fragmented; 'uncertain' when cut by the image edge; "
                            "'not graded' in round-cell mode"),
    ("Frustules", "length_um, width_um", "Long and short side of the tightest rotated bounding box"),
    ("Frustules", "equiv_diameter_um", "Diameter of a circle with the same area (the usual size for centrics)"),
    ("Frustules", "orientation_deg", "Long-axis angle, counter-clockwise from horizontal (0-180); blank for round outlines"),
    ("Frustules", "centroid_x_um, centroid_y_um", "Position from the top-left corner of the image"),
    ("Frustules", "solidity", "Area / convex-hull area; 1 = no dents"),
    ("Frustules", "rect_fill", "Area / bounding-box area; ~0.79 for ellipses, ~1 for rectangles"),
    ("Frustules", "ellipse_fit", "Overlap between the outline and its best-fit ellipse (0-1)"),
    ("Frustules", "notch_depth_ratio", "Deepest dent in the outline / width"),
    ("Frustules", "inward_corner_deg", "Sharpest inward corner of the outline; broken edges give high values"),
    ("Frustules", "crack_length_um", "Length of the longest crack-like dark line (0 if none)"),
    ("Frustules", "pore_count, porosity", "Number of detected pores; pore area / frustule area"),
    ("Frustules", "pore_density_per_um2", "Pores per square micrometre of frustule"),
    ("Frustules", "pore_nn_spacing_um", "Median centre-to-centre distance to the nearest pore"),
    ("Pores", "x_um, y_um", "Pore centre from the top-left corner of the image"),
    ("Pores", "along_um, across_um", "Pore centre relative to the frustule centre, along / across its long axis"),
    ("Pores", "diameter_um", "Equivalent-circle diameter measured at half the pore's depth (FWHM)"),
    ("Pores", "major_um, minor_um", "Longest and shortest axis of the pore (elongated areolae)"),
    ("Summary", "um_per_px, calibration", "Physical pixel size and where it came from (metadata / scale bar / manual)"),
]


def _um(value_px, um_per_px, power=1):
    if um_per_px is None or value_px is None:
        return None
    return value_px * um_per_px**power


def _nan_to_none(v):
    return None if isinstance(v, float) and not math.isfinite(v) else v


def frustule_rows(result):
    um = result.calibration.um_per_px if result.calibration.ok else None
    rows = []
    for fr in result.frustules:
        diam = [p.diameter_px for p in fr.pores]
        nn = fr.features.get("log_pore_nn_um") if fr.features else None
        rows.append({
            "image": result.name,
            "frustule_id": fr.frustule_id,
            "origin": fr.origin,
            "species": fr.species,
            "species_confidence": round(fr.species_confidence, 3) if fr.species else None,
            "morphotype": fr.morphotype,
            "view": fr.view,
            "damage": fr.damage,
            "length_um": _um(fr.length_px, um),
            "width_um": _um(fr.width_px, um),
            "equiv_diameter_um": _um(fr.equiv_diameter_px, um),
            "area_um2": _um(fr.area_px, um, 2),
            "aspect_ratio": fr.aspect_ratio,
            "orientation_deg": fr.orientation_deg,
            "centroid_x_um": _um(fr.centroid_px[0], um),
            "centroid_y_um": _um(fr.centroid_px[1], um),
            "pore_count": len(fr.pores),
            "pore_mean_diameter_um": _um(sum(diam) / len(diam), um) if diam else None,
            "pore_median_diameter_um": _um(float(pd.Series(diam).median()), um) if diam else None,
            "pore_std_diameter_um": _um(float(pd.Series(diam).std()), um) if len(diam) > 1 else None,
            "pore_density_per_um2": len(fr.pores) / _um(fr.area_px, um, 2) if um else None,
            "pore_nn_spacing_um": math.exp(nn) if nn is not None and math.isfinite(nn) else None,
            "porosity": sum(p.area_px for p in fr.pores) / fr.area_px if fr.area_px else None,
            "crack_length_um": _um(fr.crack_length_px, um),
            "solidity": fr.solidity,
            "rect_fill": fr.rect_fill,
            "ellipse_fit": fr.ellipse_iou,
            "notch_depth_ratio": fr.notch_depth_ratio,
            "inward_corner_deg": fr.inward_corner_deg,
            "touches_image_edge": fr.touches_border,
            "length_px": fr.length_px,
            "width_px": fr.width_px,
            "centroid_x_px": fr.centroid_px[0],
            "centroid_y_px": fr.centroid_px[1],
        })
    return rows


def pore_rows(result):
    um = result.calibration.um_per_px if result.calibration.ok else None
    rows = []
    for fr in result.frustules:
        for p in fr.pores:
            rows.append({
                "image": result.name,
                "frustule_id": fr.frustule_id,
                "pore_id": p.pore_id,
                "x_um": _um(p.x_px, um),
                "y_um": _um(p.y_px, um),
                "along_um": _um(p.along_px, um),
                "across_um": _um(p.across_px, um),
                "diameter_um": _um(p.diameter_px, um),
                "area_um2": _um(p.area_px, um, 2),
                "major_um": _um(p.major_px, um),
                "minor_um": _um(p.minor_px, um),
                "x_px": p.x_px,
                "y_px": p.y_px,
                "diameter_px": p.diameter_px,
            })
    return rows


def summary_row(result):
    cal = result.calibration
    damage = Counter(f.damage for f in result.frustules)
    morph = Counter(f.morphotype for f in result.frustules)
    species = Counter(f.species for f in result.frustules if f.species)
    return {
        "image": result.name,
        "frustule_count": len(result.frustules),
        "intact": damage.get("intact", 0),
        "cracked": damage.get("cracked", 0),
        "fragmented": damage.get("fragmented", 0),
        "uncertain (edge)": damage.get("uncertain", 0),
        "morphotypes": ", ".join(f"{k}: {v}" for k, v in morph.most_common()),
        "species": ", ".join(f"{k}: {v}" for k, v in species.most_common()),
        "pore_count": sum(len(f.pores) for f in result.frustules),
        "um_per_px": cal.um_per_px,
        "calibration": cal.source,
        "scale_bar_px": cal.scale_bar_length_px,
        "scale_bar_label": cal.label_text,
        "warnings": " | ".join(result.warnings),
    }


def to_dataframes(results, config=None):
    frames = {
        "Summary": pd.DataFrame([summary_row(r) for r in results]),
        "Frustules": pd.DataFrame([row for r in results for row in frustule_rows(r)]),
        "Pores": pd.DataFrame([row for r in results for row in pore_rows(r)]),
    }
    for df in frames.values():
        df.replace({float("nan"): None}, inplace=True)
    settings = {"software": f"diatom-sem-analyzer {__version__}", "run_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if config is not None:
        settings.update(config.to_flat_dict())
    frames["Settings"] = pd.DataFrame(list(settings.items()), columns=["setting", "value"])
    frames["Column guide"] = pd.DataFrame(COLUMN_GUIDE, columns=["sheet", "column", "meaning"])
    return frames


def write_excel(results, target, config=None):
    """Write the workbook to a path or a binary file-like object."""
    frames = to_dataframes(results, config)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet, df in frames.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            ws.freeze_panes = "A2"
            for idx, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(f"{v:.4g}" if isinstance(v, float) else str(v))
                                               for v in df[col].head(200)])
                ws.column_dimensions[ws.cell(1, idx).column_letter].width = min(60, width + 2)
                if df[col].dtype.kind == "f":
                    for cell in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                        cell[0].number_format = "0.000"
    return frames
