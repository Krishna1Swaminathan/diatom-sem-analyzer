"""Readers for labelled diatom image collections, used to test and to build species libraries.

Two layouts cover the public datasets:

* **Pascal VOC** (e.g. the Kaggle "Diatom Dataset" by Gündüz et al.): full images plus one XML
  file per image listing each diatom's species and bounding box.
* **Folder per species** (e.g. ADIAC, UDE Diatoms in the Wild, Pu et al.): one sub-folder per
  species, each holding images of single specimens.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@dataclass
class BoxLabel:
    species: str
    box: tuple  # (x0, y0, x1, y1) in pixels


@dataclass
class LabelledImage:
    path: Path
    boxes: list = field(default_factory=list)


def _index_images(root):
    index = {}
    for p in Path(root).rglob("*"):
        if p.suffix.lower() in IMAGE_SUFFIXES:
            index.setdefault(p.name.lower(), p)
            index.setdefault(p.stem.lower(), p)
    return index


def load_voc(root):
    """All images in ``root`` that have a Pascal VOC XML annotation (searched recursively)."""
    root = Path(root)
    images = _index_images(root)
    out = []
    for xml_path in sorted(root.rglob("*.xml")):
        try:
            tree = ET.parse(xml_path).getroot()
        except ET.ParseError:
            continue
        filename = (tree.findtext("filename") or "").strip()
        path = images.get(filename.lower()) or images.get(Path(filename).stem.lower()) \
            or images.get(xml_path.stem.lower())
        if path is None:
            continue
        boxes = []
        for obj in tree.iter("object"):
            bb = obj.find("bndbox")
            if bb is None:
                continue
            try:
                box = tuple(int(round(float(bb.findtext(k)))) for k in ("xmin", "ymin", "xmax", "ymax"))
            except (TypeError, ValueError):
                continue
            boxes.append(BoxLabel((obj.findtext("name") or "unknown").strip(), box))
        if boxes:
            out.append(LabelledImage(path, boxes))
    return out


def load_species_folders(root):
    """{species: [image paths]} for a folder-per-species collection."""
    root = Path(root)
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("__", "."))):
        files = sorted(p for p in d.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
        if files:
            out[d.name] = files
    return out


def box_iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def frustule_box(fr):
    r0, c0, r1, c1 = fr.bbox
    return (c0, r0, c1, r1)


def greedy_match(scores, threshold=0.5):
    """Pairs (i, j) maximising score, each index used once, score >= threshold."""
    cand = sorted(((s, i, j) for i, row in enumerate(scores) for j, s in enumerate(row) if s >= threshold),
                  reverse=True)
    used_i, used_j, pairs = set(), set(), []
    for s, i, j in cand:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            pairs.append((i, j, s))
    return pairs
