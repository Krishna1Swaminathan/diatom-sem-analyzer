"""The app, run headlessly the way a user would click through it."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit_image_coordinates")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _start():
    return AppTest.from_file(APP, default_timeout=300).run()


def _metric(at, label):
    """A number from the result tiles (rendered as HTML, so read from the markdown)."""
    import re
    html = next(m.value for m in at.markdown if m.value.startswith("<div class='da-stats'>"))
    return re.search(rf"{label}</div><div class='v'>(\d+)<", html).group(1)


def test_opens_on_step_one_without_errors():
    at = _start()
    assert not at.exception
    assert any("Add your images" in m.value for m in at.markdown)
    assert any("example images" in b.label for b in at.button)


def test_example_images_walk_through():
    at = _start()
    next(b for b in at.button if "example images" in b.label).click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    for step in ("What does your sample look like?", "Check each image, and fix any mistakes",
                 "Save your results"):
        assert step in page
    assert int(_metric(at, "Diatoms found")) > 0
    assert any("Scale:" in s.value for s in at.success)

    at.radio(key="sample_type").set_value("manual").run()
    assert not at.exception
    assert int(_metric(at, "Diatoms found")) == 0

    at.radio(key="sample_type").set_value("round").run()
    assert not at.exception
    assert any(n.label.startswith("About how wide is one cell") for n in at.number_input)
