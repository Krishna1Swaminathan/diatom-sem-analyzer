import io
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

TIFF_SUFFIXES = {".tif", ".tiff"}


def _to_gray_float(arr):
    arr = np.asarray(arr)
    if arr.ndim == 3:
        if arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
            arr = np.moveaxis(arr, 0, -1)
        if arr.shape[-1] == 4:
            arr = arr[..., :3]
        arr = arr[..., :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    elif arr.ndim > 3:
        return _to_gray_float(arr[0])
    if np.issubdtype(arr.dtype, np.integer):
        # Scale by the container's range so pure-white databar text stays exactly 1.0.
        top = 255 if arr.max() <= 255 else np.iinfo(arr.dtype).max
        return (arr.astype(np.float32) / top).clip(0, 1)
    arr = arr.astype(np.float32)
    lo, hi = float(arr.min()), float(arr.max())
    return (arr - lo) / (hi - lo) if hi > lo else np.zeros_like(arr)


def load_image(source, name=None):
    """Load an image from a path or raw bytes into a 2-D float32 array in [0, 1]."""
    if isinstance(source, (str, Path)):
        name = name or Path(source).name
        data = Path(source).read_bytes()
    else:
        data = bytes(source)
    suffix = Path(name or "").suffix.lower()
    if suffix in TIFF_SUFFIXES or data[:4] in (b"II*\x00", b"MM\x00*"):
        arr = tifffile.imread(io.BytesIO(data), key=0)
    else:
        with Image.open(io.BytesIO(data)) as im:
            arr = np.array(im.convert("I") if im.mode in ("I;16", "I;16B", "I") else im.convert("RGB")
                           if im.mode in ("P", "CMYK", "YCbCr", "LA", "RGBA") else im)
    return _to_gray_float(arr)
