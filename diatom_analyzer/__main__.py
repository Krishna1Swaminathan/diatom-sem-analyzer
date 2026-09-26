"""Batch command line: python -m diatom_analyzer IMAGES_OR_FOLDERS -o results.xlsx"""

import argparse
import sys
from pathlib import Path

import cv2

from .classification import IMAGE_SUFFIXES, SpeciesLibrary
from .config import AnalysisConfig
from .export import write_excel
from .pipeline import analyze_image
from .visualize import render_overlay


def _expand(inputs):
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            yield from sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        else:
            yield p


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m diatom_analyzer",
                                     description="Measure diatom frustules and pores in SEM images.")
    parser.add_argument("inputs", nargs="+", help="image files or folders")
    parser.add_argument("-o", "--output", default="diatom_results.xlsx", help="Excel workbook to write")
    parser.add_argument("--overlays", help="folder for annotated PNGs")
    parser.add_argument("--um-per-px", type=float, help="override: micrometres per pixel")
    parser.add_argument("--bar-um", type=float, help="override: length in µm of the detected scale bar")
    parser.add_argument("--library", default="species_library", help="species reference folder")
    parser.add_argument("--method", choices=["classical", "cellpose"], default="classical")
    parser.add_argument("--min-size-um", type=float, help="ignore objects smaller than this")
    parser.add_argument("--no-ocr", action="store_true", help="do not read scale-bar text")
    args = parser.parse_args(argv)

    config = AnalysisConfig()
    config.segmentation.method = args.method
    if args.min_size_um:
        config.segmentation.min_frustule_um = args.min_size_um
    library = SpeciesLibrary(args.library)
    overlay_dir = Path(args.overlays) if args.overlays else None
    if overlay_dir:
        overlay_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for path in _expand(args.inputs):
        try:
            res = analyze_image(path, config=config, manual_um_per_px=args.um_per_px,
                                manual_bar_um=args.bar_um, library=library, use_ocr=not args.no_ocr)
        except Exception as exc:  # keep going through a batch
            print(f"[skip] {path.name}: {exc}", file=sys.stderr)
            continue
        cal = res.calibration
        scale = f"{cal.um_per_px:.4g} µm/px ({cal.source})" if cal.ok else "NO SCALE"
        print(f"{path.name}: {len(res.frustules)} frustules, "
              f"{sum(len(f.pores) for f in res.frustules)} pores, {scale}")
        for w in res.warnings:
            print(f"   warning: {w}")
        if overlay_dir:
            cv2.imwrite(str(overlay_dir / f"{path.stem}_annotated.png"),
                        cv2.cvtColor(render_overlay(res), cv2.COLOR_RGB2BGR))
        res.image = res.labels = None  # free memory in long batches
        results.append(res)

    if not results:
        print("No images analysed.", file=sys.stderr)
        return 1
    write_excel(results, args.output, config)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
