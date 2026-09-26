import io

import numpy as np
import pytest
from PIL import Image

from diatom_analyzer.pipeline import analyze_image
from diatom_analyzer.synthetic import DEMO_SCENE, FrustuleSpec, render_scene
from tests.conftest import match_truth, png_bytes


def test_counts_every_frustule(demo_result):
    result, truth = demo_result
    assert len(result.frustules) == len(truth["frustules"])


def test_damage_grades(demo_result):
    result, truth = demo_result
    for gt, fr in match_truth(result, truth):
        assert fr.damage == gt["damage"], f"{gt['kind']} at ({gt['cx_um']}, {gt['cy_um']})"


def test_sizes_in_micrometres(demo_result):
    result, truth = demo_result
    um = truth["um_per_px"]
    for gt, fr in match_truth(result, truth):
        if gt["damage"] == "fragmented":
            continue  # a fragment is shorter than the intact valve by design
        assert fr.length_px * um == pytest.approx(gt["length_um"], rel=0.03)
        assert fr.width_px * um == pytest.approx(gt["width_um"], rel=0.05)


def test_orientation(demo_result):
    result, truth = demo_result
    for gt, fr in match_truth(result, truth):
        if gt["kind"] == "centric":
            assert fr.orientation_deg is None  # round outline: no meaningful long axis
            continue
        diff = abs((fr.orientation_deg - gt["angle_deg"] % 180 + 90) % 180 - 90)
        assert diff < 2.0


def test_view_and_morphotype(demo_result):
    result, truth = demo_result
    for gt, fr in match_truth(result, truth):
        expected_view = "girdle" if gt["kind"] == "girdle" else "valve"
        assert fr.view == expected_view
        if gt["damage"] == "fragmented":
            assert fr.morphotype == "fragment"
        elif gt["kind"] == "centric":
            assert fr.morphotype == "centric"
        elif gt["kind"] == "pennate":
            assert fr.morphotype.startswith("pennate")
        else:
            assert fr.morphotype == "girdle view"


def test_pores(demo_result):
    result, truth = demo_result
    um = truth["um_per_px"]
    for gt, fr in match_truth(result, truth):
        if gt["damage"] != "intact":
            continue
        assert len(fr.pores) == pytest.approx(len(gt["pores"]), rel=0.05)
        diam = np.median([p.diameter_px for p in fr.pores]) * um
        assert diam == pytest.approx(gt["pore_diameter_um"], abs=0.04)
        truth_xy = np.array([[p["x_px"], p["y_px"]] for p in gt["pores"]])
        for p in fr.pores[:20]:
            nearest = np.min(np.hypot(*(truth_xy - [p.x_px, p.y_px]).T))
            assert nearest < 2.0  # pore centres within 2 px (0.1 µm)


def test_touching_pair_is_split_and_long_pennate_is_not():
    specs = [FrustuleSpec("centric", 12, 12, 8, 8), FrustuleSpec("centric", 19.5, 12, 8, 8),
             FrustuleSpec("pennate", 25, 28, 40, 4, angle_deg=5)]
    img, _ = render_scene(specs, field_um=(51.2, 38.4), bar_style="none", seed=7)
    res = analyze_image(png_bytes(img), name="pair.png", manual_um_per_px=0.05)
    assert len(res.frustules) == 3


def test_edge_frustule_is_uncertain():
    specs = [FrustuleSpec("centric", 2.0, 15, 10, 10), FrustuleSpec("centric", 25, 15, 10, 10)]
    img, _ = render_scene(specs, bar_style="none", seed=8)
    res = analyze_image(png_bytes(img), name="edge.png", manual_um_per_px=0.05)
    grades = sorted((f.centroid_px[0], f.damage) for f in res.frustules)
    assert grades[0][1] == "uncertain"
    assert grades[1][1] == "intact"


def test_scale_invariance():
    """The same physical scene imaged at two magnifications gives the same µm measurements."""
    lengths = []
    for um in (0.025, 0.05):
        img, _ = render_scene(DEMO_SCENE[:3], um_per_px=um, bar_style="none", seed=3)
        res = analyze_image(png_bytes(img), name="s.png", manual_um_per_px=um)
        lengths.append(sorted(f.length_px * um for f in res.frustules))
    assert np.allclose(lengths[0], lengths[1], rtol=0.02)


def test_without_scale_still_counts(demo_scene):
    data, _ = demo_scene
    res = analyze_image(data, name="d.png", use_ocr=False)
    assert not res.calibration.ok
    assert len(res.frustules) == 7
    assert any("scale" in w.lower() for w in res.warnings)


def test_bright_substrate_dark_frustules():
    img, _ = render_scene(DEMO_SCENE[:3], bar_style="none", seed=9)
    inverted = 255 - img
    res = analyze_image(png_bytes(inverted), name="inv.png", manual_um_per_px=0.05)
    assert len(res.frustules) == 3


def test_16bit_tiff(tmp_path):
    img, _ = render_scene(DEMO_SCENE[:2], bar_style="none", seed=10)
    import tifffile
    path = tmp_path / "deep.tif"
    tifffile.imwrite(path, img.astype(np.uint16) * 257)
    res = analyze_image(path, manual_um_per_px=0.05)
    assert len(res.frustules) == 2


def test_rgb_jpeg():
    img, _ = render_scene(DEMO_SCENE[:2], bar_style="none", seed=11)
    buf = io.BytesIO()
    Image.fromarray(img).convert("RGB").save(buf, format="JPEG", quality=90)
    res = analyze_image(buf.getvalue(), name="c.jpg", manual_um_per_px=0.05)
    assert len(res.frustules) == 2


def test_round_cell_mode_finds_crowded_centrics():
    from diatom_analyzer.config import AnalysisConfig
    from diatom_analyzer.synthetic import FrustuleSpec
    specs = [FrustuleSpec("centric", 6 + 4.2 * i, 6 + 4.2 * j, 4.0, 4.0, pore_diameter_um=0.3, pore_spacing_um=0.7)
             for i in range(10) for j in range(7)]  # a touching 10 x 7 grid of 4 µm cells
    img, _ = render_scene(specs, bar_style="none", seed=31)
    cfg = AnalysisConfig()
    cfg.segmentation.method = "round_cells"
    cfg.segmentation.cell_diameter_um = (3.0, 5.0)
    res = analyze_image(png_bytes(img), name="grid.png", manual_um_per_px=0.05, config=cfg)
    assert len(res.frustules) >= 0.8 * len(specs)
    diam = np.median([f.equiv_diameter_px * 0.05 for f in res.frustules])
    assert diam == pytest.approx(4.0, rel=0.1)
    assert all(f.damage == "not graded" for f in res.frustules)


def test_click_to_add_and_remove():
    from diatom_analyzer.synthetic import FrustuleSpec
    specs = [FrustuleSpec("centric", 12, 12, 8, 8), FrustuleSpec("pennate", 32, 20, 16, 5, angle_deg=20)]
    img, truth = render_scene(specs, bar_style="none", seed=41)
    data = png_bytes(img)
    auto = analyze_image(data, name="e.png", manual_um_per_px=0.05)
    assert len(auto.frustules) == 2
    cx, cy = specs[0].cx_um / 0.05, specs[0].cy_um / 0.05
    # remove the centric, then add it back by clicking near (not exactly on) its centre
    remove = ("remove", cx, cy, cx, cy, 0)
    removed = analyze_image(data, name="e.png", manual_um_per_px=0.05, edits=(remove,))
    assert len(removed.frustules) == 1
    # click near (not exactly on) the centre, with a size hint 25 % too large
    readded = analyze_image(data, name="e.png", manual_um_per_px=0.05,
                            edits=(remove, ("add", cx + 10, cy - 8, cx + 10, cy - 8, 10 / 0.05)))
    assert len(readded.frustules) == 2
    manual = [f for f in readded.frustules if f.origin == "manual"]
    assert len(manual) == 1
    assert manual[0].equiv_diameter_px * 0.05 == pytest.approx(8.0, rel=0.1)  # traced the real outline


def test_drag_along_axis_traces_pennate():
    from diatom_analyzer.synthetic import FrustuleSpec
    import math
    spec = FrustuleSpec("pennate", 25, 19, 20, 5, angle_deg=30, profile="lanceolate")
    img, truth = render_scene([spec], bar_style="none", seed=43)
    data = png_bytes(img)
    cx, cy, half = spec.cx_um / 0.05, spec.cy_um / 0.05, spec.length_um / 0.05 / 2 * 0.95
    dx, dy = half * math.cos(math.radians(30)), -half * math.sin(math.radians(30))
    remove = ("remove", cx, cy, cx, cy, 0)
    res = analyze_image(data, name="d.png", manual_um_per_px=0.05,
                        edits=(remove, ("add", cx - dx, cy - dy, cx + dx, cy + dy, 0)))
    assert len(res.frustules) == 1 and res.frustules[0].origin == "manual"
    fr = res.frustules[0]
    assert fr.length_px * 0.05 == pytest.approx(truth["frustules"][0]["mask_length_um"], rel=0.05)
    assert fr.area_px == pytest.approx(truth["frustules"][0]["area_px"], rel=0.1)


def test_training_example_export(tmp_path):
    import cv2
    from diatom_analyzer.editing import save_training_example
    img, _ = render_scene(DEMO_SCENE[:2], bar_style="none", seed=42)
    res = analyze_image(png_bytes(img), name="t.png", manual_um_per_px=0.05)
    image_path, mask_path = save_training_example(res.image[: res.analysis_height], res.labels, tmp_path, "t")
    masks = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    assert masks.dtype == np.uint16 and masks.max() == len(res.frustules)
    assert cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE).shape == masks.shape
