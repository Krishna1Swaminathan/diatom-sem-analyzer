"""The dataset importers and evaluators, run on small fake datasets in the real on-disk formats."""

import json

import pytest

from diatom_analyzer.classification import SpeciesLibrary
from diatom_analyzer.datasets import box_iou, greedy_match, load_species_folders, load_voc
from diatom_analyzer.evaluate import build_library, run_folders, run_voc
from diatom_analyzer.synthetic import random_frame, specimen_crop
from tests.conftest import png_bytes

SPECIES = ["Cyclotella-like", "Navicula-like", "Triceratium-like"]


def _voc_xml(filename, w, h, objects):
    objs = "".join(
        f"<object><name>{name}</name><pose>Unspecified</pose><bndbox><xmin>{x0}</xmin><ymin>{y0}</ymin>"
        f"<xmax>{x1}</xmax><ymax>{y1}</ymax></bndbox></object>" for name, (x0, y0, x1, y1) in objects)
    return (f"<annotation><folder>images</folder><filename>{filename}</filename><size><width>{w}</width>"
            f"<height>{h}</height><depth>1</depth></size>{objs}</annotation>")


@pytest.fixture(scope="module")
def voc_dataset(tmp_path_factory):
    """Kaggle-style layout: images/ and annotations/ side by side."""
    root = tmp_path_factory.mktemp("voc")
    (root / "images").mkdir()
    (root / "annotations").mkdir()
    for seed in range(6):
        img, truth, _ = random_frame(seed + 50, species=SPECIES, bar_style="none")
        name = f"img_{seed:03d}.png"
        (root / "images" / name).write_bytes(png_bytes(img))
        objects = []
        for f in truth["frustules"]:
            r0, c0, r1, c1 = f["mask_bbox"]
            objects.append((f["species"], (c0, r0, c1, r1)))
        (root / "annotations" / f"img_{seed:03d}.xml").write_text(
            _voc_xml(name, img.shape[1], img.shape[0], objects))
    return root


@pytest.fixture(scope="module")
def folder_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("folders")
    for s_idx, species in enumerate(SPECIES):
        (root / species).mkdir()
        for j in range(5):
            img, _ = specimen_crop(species, seed=500 + 10 * s_idx + j)
            (root / species / f"{j}.png").write_bytes(png_bytes(img))
    return root


def test_load_voc(voc_dataset):
    items = load_voc(voc_dataset)
    assert len(items) == 6
    assert all(item.path.exists() and item.boxes for item in items)
    assert {b.species for item in items for b in item.boxes} <= set(SPECIES)


def test_box_iou_and_matching():
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    pairs = greedy_match([[0.9, 0.6], [0.7, 0.1]], 0.5)
    assert sorted((i, j) for i, j, _ in pairs) == [(0, 0)] or sorted((i, j) for i, j, _ in pairs) == [(0, 0)]


def test_run_voc(voc_dataset, tmp_path):
    data = run_voc(voc_dataset, um_per_px=None, train_fraction=0.5, shots=3, out=tmp_path)
    assert data["detection"]["recall"] > 0.9
    assert data["detection"]["precision"] > 0.9
    assert data["species"]["accuracy"] > 0.8
    assert json.loads((tmp_path / "report.json").read_text())["images"] == 6


def test_run_folders(folder_dataset, tmp_path):
    assert set(load_species_folders(folder_dataset)) == set(SPECIES)
    stats = run_folders(folder_dataset, shots=2, max_test=3, um_per_px=0.05, out=tmp_path)
    assert stats["n"] == 9
    assert stats["accuracy"] >= 0.8


def test_build_library_from_folders(folder_dataset, tmp_path):
    out = tmp_path / "lib"
    added = build_library(folder_dataset, "folders", out, shots=2, um_per_px=0.05)
    assert all(added[s] == 2 for s in SPECIES)
    lib = SpeciesLibrary(out)
    assert sorted(lib.species) == sorted(SPECIES)
    assert len(list(out.rglob("*.png"))) == 6  # previews for the app's gallery


def test_build_library_from_voc(voc_dataset, tmp_path):
    out = tmp_path / "lib"
    build_library(voc_dataset, "voc", out, shots=2)
    assert set(SpeciesLibrary(out).species) <= set(SPECIES)
    assert len(SpeciesLibrary(out)) >= 4
