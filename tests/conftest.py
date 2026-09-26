import io

import pytest
from PIL import Image

from diatom_analyzer.synthetic import DEMO_SCENE, render_scene


def png_bytes(img):
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def demo_scene():
    """(png bytes, ground truth) of the demo field with a databar scale bar."""
    img, truth = render_scene(DEMO_SCENE, seed=0)
    return png_bytes(img), truth


@pytest.fixture(scope="session")
def demo_result(demo_scene):
    from diatom_analyzer.pipeline import analyze_image

    data, truth = demo_scene
    return analyze_image(data, name="demo.png", manual_um_per_px=truth["um_per_px"]), truth


def match_truth(result, truth):
    """Pair each ground-truth frustule with the detected frustule whose centroid is nearest."""
    um = truth["um_per_px"]
    pairs = []
    for gt in truth["frustules"]:
        cx, cy = gt["cx_um"] / um, gt["cy_um"] / um
        best = min(result.frustules, key=lambda f: (f.centroid_px[0] - cx) ** 2 + (f.centroid_px[1] - cy) ** 2)
        pairs.append((gt, best))
    return pairs
