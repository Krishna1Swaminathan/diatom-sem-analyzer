"""Train a Cellpose detection model on the lab's own corrected outlines.

Save examples from the app (*Training labels* tab: `name.png` + `name_masks.png`), then:

    python -m diatom_analyzer.train training_data                 # fine-tune the pretrained cyto3 model
    python -m diatom_analyzer.train training_data --from-scratch  # no download needed (offline)

The trained model is written to `models/`; the app then offers *Use the lab's trained model* in
step 2. A share of the examples is held back and the
report gives precision and recall on them, so you can see whether more examples are needed.
Requires `pip install "cellpose>=3.1,<4"` (the compact Cellpose 3 network trains on a laptop CPU).
"""

import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np


def load_examples(folder):
    """(names, images, masks) from `*_masks.png` files and their matching images."""
    folder = Path(folder)
    names, images, masks = [], [], []
    for mask_path in sorted(folder.glob("*_masks.png")):
        stem = mask_path.name[: -len("_masks.png")]
        image_path = next((p for p in (folder / f"{stem}.png", folder / f"{stem}.tif", folder / f"{stem}.jpg")
                           if p.exists()), None)
        if image_path is None:
            continue
        mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if mask is None or image is None or mask.shape != image.shape or mask.max() == 0:
            continue
        names.append(stem)
        images.append(image)
        masks.append(mask.astype(np.int32))
    return names, images, masks


def detection_scores(true_masks, pred_masks, iou=0.5):
    """Precision, recall and F1 over a set of images, matching outlines at IoU >= ``iou``."""
    from .datasets import greedy_match
    from .evaluate import mask_iou_matrix

    tp = fp = fn = 0
    for t, p in zip(true_masks, pred_masks):
        pairs = greedy_match(mask_iou_matrix(t, p), iou) if t.max() and p.max() else []
        tp += len(pairs)
        fp += int(p.max()) - len(pairs)
        fn += int(t.max()) - len(pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "true": tp + fn, "predicted": tp + fp, "matched": tp}


def _cellpose():
    try:
        from cellpose import models, train
    except ImportError:
        sys.exit('Cellpose is not installed. Run: pip install "cellpose>=3.1,<4"')
    return models, train


def predict(model, images, diameter=None):
    out = []
    for image in images:
        result = model.eval(image, diameter=diameter, channels=[0, 0])
        out.append(np.asarray(result[0], dtype=np.int32))
    return out


def train_model(folder, out_dir="models", name="diatoms", epochs=300, learning_rate=0.1, from_scratch=False,
                test_fraction=0.25, seed=0, gpu=False):
    models, train = _cellpose()
    names, images, masks = load_examples(folder)
    if len(images) < 2:
        sys.exit(f"Need at least 2 training examples in {folder} (found {len(images)}).")
    order = list(range(len(images)))
    random.Random(seed).shuffle(order)
    n_test = max(1, int(round(test_fraction * len(images)))) if len(images) >= 4 else 0
    test_idx, train_idx = order[:n_test], order[n_test:]
    pick = lambda idx, xs: [xs[i] for i in idx]  # noqa: E731

    if from_scratch:
        model = models.CellposeModel(gpu=gpu, pretrained_model=False, diam_mean=30.0)
    else:
        model = models.CellposeModel(gpu=gpu, model_type="cyto3")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    result = train.train_seg(
        model.net, train_data=pick(train_idx, images), train_labels=pick(train_idx, masks),
        test_data=pick(test_idx, images) or None, test_labels=pick(test_idx, masks) or None,
        channels=[0, 0], normalize=True, n_epochs=epochs, learning_rate=learning_rate, weight_decay=1e-4,
        SGD=True, min_train_masks=1, save_path=str(out_dir), model_name=name)
    model_path = Path(result[0] if isinstance(result, (tuple, list)) else result)
    final = out_dir / name  # Cellpose writes into save_path/models/; keep models where the app looks
    if model_path.resolve() != final.resolve() and model_path.exists():
        shutil.move(str(model_path), final)
        try:
            model_path.parent.rmdir()
        except OSError:
            pass
        model_path = final
    minutes = (time.time() - started) / 60

    report = {"model": str(model_path), "examples": len(images), "train": len(train_idx), "test": len(test_idx),
              "epochs": epochs, "from_scratch": from_scratch, "minutes": round(minutes, 1)}
    if test_idx:
        trained = models.CellposeModel(gpu=gpu, pretrained_model=str(model_path))
        diameter = float(getattr(trained, "diam_labels", 0)) or None
        preds = predict(trained, pick(test_idx, images), diameter)
        report["held_out"] = detection_scores(pick(test_idx, masks), preds)
        report["diameter_px"] = diameter
    (out_dir / f"{name}_report.json").write_text(json.dumps(report, indent=1))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m diatom_analyzer.train", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="folder of name.png + name_masks.png examples")
    parser.add_argument("--out", default="models")
    parser.add_argument("--name", default="diatoms")
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--from-scratch", action="store_true", help="do not start from the pretrained cyto3 model")
    parser.add_argument("--gpu", action="store_true")
    a = parser.parse_args(argv)
    report = train_model(a.folder, a.out, a.name, a.epochs, a.learning_rate, a.from_scratch, gpu=a.gpu)
    print(json.dumps(report, indent=1))
    held = report.get("held_out")
    if held:
        print(f"\nOn {report['test']} held-out image(s): precision {held['precision']:.0%}, "
              f"recall {held['recall']:.0%} ({held['matched']}/{held['true']} outlines found).")
    print(f"Model saved to {report['model']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
