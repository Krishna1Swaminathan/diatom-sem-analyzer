"""Smoke test of the Cellpose training path (skipped when Cellpose is not installed)."""

import json

import pytest

from diatom_analyzer.editing import save_training_example
from diatom_analyzer.synthetic import FrustuleSpec, render_scene

pytest.importorskip("cellpose")


def test_train_writes_model_and_report(tmp_path):
    from diatom_analyzer.train import load_examples, train_model

    data = tmp_path / "training"
    for seed in range(4):
        specs = [FrustuleSpec("centric", 3 + 5 * i, 4, 3, 3) for i in range(3)]
        img, _, labels = render_scene(specs, field_um=(16, 8), um_per_px=0.1, seed=seed, bar_style="none",
                                      return_labels=True)
        save_training_example(img / 255.0, labels, data, f"ex{seed}")
    assert len(load_examples(data)[0]) == 4

    report = train_model(data, out_dir=tmp_path / "models", name="smoke", epochs=2, from_scratch=True)
    assert (tmp_path / "models" / "smoke").exists()
    assert report["train"] == 3 and report["test"] == 1
    assert "held_out" in report
    assert json.loads((tmp_path / "models" / "smoke_report.json").read_text())["epochs"] == 2
