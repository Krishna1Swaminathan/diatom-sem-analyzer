import numpy as np
import pytest
import tifffile

from diatom_analyzer.calibration import (calibrate, calibration_from_metadata, find_databar_top,
                                         find_scale_bar_candidates, ocr_available)
from diatom_analyzer.loading import load_image
from diatom_analyzer.synthetic import DEMO_SCENE, render_scene, save_tiff_fei, save_tiff_imagej

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="Tesseract OCR not installed")


@pytest.fixture(scope="module")
def plain_frame():
    img, truth = render_scene(DEMO_SCENE[:3], bar_style="none", seed=4)
    return img, truth


def test_databar_detected(demo_scene):
    from tests.conftest import png_bytes  # noqa: F401
    data, truth = demo_scene
    image = load_image(data, name="demo.png")
    assert find_databar_top(image) == pytest.approx(truth["analysis_height"], abs=2)


def test_no_databar_on_plain_frame(plain_frame):
    img, _ = plain_frame
    assert find_databar_top(img / 255.0) == img.shape[0]


@pytest.mark.parametrize("um_per_px,bar_um", [(0.025, 5), (0.05, 10), (0.1, 20)])
def test_scale_bar_length(um_per_px, bar_um):
    img, _ = render_scene(DEMO_SCENE[:2], um_per_px=um_per_px, scale_bar_um=bar_um, seed=1)
    bars = find_scale_bar_candidates(img / 255.0)
    assert bars, "scale bar not found"
    assert bars[0]["length_px"] == pytest.approx(bar_um / um_per_px, rel=0.01)


@needs_ocr
@pytest.mark.parametrize("um_per_px,bar_um,style", [(0.05, 10, "databar"), (0.05, 10, "inset"),
                                                     (0.025, 5, "databar"), (0.002, 0.5, "databar")])
def test_scale_from_bar_label(um_per_px, bar_um, style):
    specs = DEMO_SCENE[:2] if um_per_px >= 0.01 else []
    field = (51.2, 38.4) if um_per_px >= 0.01 else (4.0, 3.0)
    img, _ = render_scene(specs, um_per_px=um_per_px, scale_bar_um=bar_um, bar_style=style, field_um=field)
    cal = calibrate(img / 255.0)
    assert cal.source == "scale_bar"
    assert cal.um_per_px == pytest.approx(um_per_px, rel=0.01)


def test_manual_bar_value_without_ocr(demo_scene):
    data, truth = demo_scene
    cal = calibrate(load_image(data, name="d.png"), manual_bar_um=10, use_ocr=False)
    assert cal.um_per_px == pytest.approx(truth["um_per_px"], rel=0.01)
    assert "user" in cal.source


def test_no_ocr_and_no_metadata_gives_no_scale(demo_scene):
    data, _ = demo_scene
    cal = calibrate(load_image(data, name="d.png"), use_ocr=False)
    assert not cal.ok
    assert cal.scale_bar_length_px == pytest.approx(200, abs=1)  # the UI can still ask what it shows


def test_fei_metadata(tmp_path, plain_frame):
    img, _ = plain_frame
    path = tmp_path / "fei.tif"
    save_tiff_fei(path, img, 0.0123)
    um, source, _ = calibration_from_metadata(path)
    assert um == pytest.approx(0.0123)
    assert "FEI" in source


def test_imagej_metadata(tmp_path, plain_frame):
    img, _ = plain_frame
    path = tmp_path / "ij.tif"
    save_tiff_imagej(path, img, 0.037)
    um, source, _ = calibration_from_metadata(path)
    assert um == pytest.approx(0.037, rel=1e-3)
    assert "ImageJ" in source


def test_screen_dpi_tag_is_not_a_calibration(tmp_path, plain_frame):
    img, _ = plain_frame
    path = tmp_path / "dpi.tif"
    tifffile.imwrite(path, img, resolution=(300, 300), resolutionunit="INCH")
    assert calibration_from_metadata(path) is None


def test_hitachi_sidecar(tmp_path, plain_frame):
    img, _ = plain_frame
    path = tmp_path / "hitachi.tif"
    tifffile.imwrite(path, img)
    path.with_suffix(".txt").write_text("[SemImageFile]\nPixelSize=24.8\n")
    um, source, _ = calibration_from_metadata(path)
    assert um == pytest.approx(0.0248)
    assert "Hitachi" in source


def test_jeol_sidecar(tmp_path, plain_frame):
    img, _ = plain_frame
    path = tmp_path / "jeol.tif"
    tifffile.imwrite(path, img)
    path.with_suffix(".txt").write_text("$CM_MAG 5000\n$$SM_MICRON_BAR 160\n$$SM_MICRON_MARKER 5um\n")
    um, source, _ = calibration_from_metadata(path)
    assert um == pytest.approx(5 / 160)
    assert "JEOL" in source


@needs_ocr
def test_resized_image_disagreement_is_flagged(tmp_path):
    """Metadata written for the original pixels but the image was downsampled 2x afterwards."""
    img, _ = render_scene(DEMO_SCENE[:2], um_per_px=0.025, scale_bar_um=10, seed=2)
    half = img[::2, ::2]
    path = tmp_path / "resized.tif"
    save_tiff_fei(path, half, 0.025)
    cal = calibrate(load_image(path), path=path)
    assert "warning" in cal.details
    assert cal.details["scale_bar_um_per_px"] == pytest.approx(0.05, rel=0.02)


def test_metadata_takes_priority_over_bar(tmp_path):
    img, _ = render_scene(DEMO_SCENE[:2], seed=2)
    path = tmp_path / "both.tif"
    save_tiff_fei(path, img, 0.05)
    cal = calibrate(load_image(path), path=path)
    assert cal.source.startswith("metadata")
    assert "warning" not in cal.details
    assert np.isclose(cal.um_per_px, 0.05)


# --------------------------------------------------------------------------- lab instrument formats

HITACHI_S4700_TXT = """[SemImageFile]
InstructName=S-4700
DataSize=1280x960
Magnification=15000
MicronMarker=3000
Condition=Vacc=10kV   Mag=x15.0k   WD=8.1mm
"""


def test_hitachi_s4700_txt_uses_magnification():
    from diatom_analyzer.calibration import parse_sidecar_text
    um, source, details = parse_sidecar_text(HITACHI_S4700_TXT)
    assert um == pytest.approx(127_000 / 15000 / 1280)  # 6.615 nm/px, confirmed on the lab's tick rulers
    assert "Hitachi" in source
    assert details["marker_um"] == pytest.approx(3.0)


def test_phenom_embedded_xml():
    from diatom_analyzer.calibration import calibration_from_metadata
    img, _ = render_scene(DEMO_SCENE[:1], bar_style="none", seed=3)
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG")
    xml = (b'<?xml version="1.0"?><FeiImage><databarHeight>64</databarHeight>'
           b'<pixelWidth unit="um">0.694952</pixelWidth><instrument><edition>G4 Phenom ProX</edition>'
           b'</instrument></FeiImage>')
    um, source, details = calibration_from_metadata(data=buf.getvalue() + xml)
    assert um == pytest.approx(0.694952)
    assert details["databar_height"] == 64
    assert "Phenom" in source


def _hitachi_strip(width=1280, height=960, strip=144, span=455, ticks=11):
    img = np.full((height, width), 0.4)
    img[height - strip:] = 0.0
    x_end = width - 92
    for k in range(ticks):
        x = int(round(x_end - span + k * span / (ticks - 1)))
        img[height - strip + 2:height - strip + 14, x:x + 2] = 1.0
    return img


def test_tick_ruler_detected():
    from diatom_analyzer.calibration import find_tick_ruler
    img = _hitachi_strip()
    ruler = find_tick_ruler(img, databar_top=816)
    assert ruler is not None
    assert ruler["ticks"] == 11
    assert ruler["length_px"] == pytest.approx(455, abs=2)


def test_tick_ruler_with_sidecar_marker():
    img = _hitachi_strip()
    cal = calibrate(img, sidecar_text=HITACHI_S4700_TXT, use_ocr=False)
    assert cal.um_per_px == pytest.approx(0.006615, rel=1e-3)
    assert cal.details["scale_bar_um_per_px"] == pytest.approx(3.0 / 455, rel=0.01)
    assert "warning" not in cal.details


@pytest.mark.parametrize("text,digits", [("47.2", 3), ("120", 2), ("0.50", 1), ("8", 1), ("94.8", 3), ("2.5", 2)])
def test_significant_digits(text, digits):
    from diatom_analyzer.calibration import _significant_digits
    assert _significant_digits(text) == digits
