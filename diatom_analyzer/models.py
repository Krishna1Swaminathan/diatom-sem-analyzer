from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Calibration:
    um_per_px: Optional[float]
    source: str  # "metadata:<kind>", "scale_bar", "manual", or "none"
    details: dict = field(default_factory=dict)
    scale_bar_bbox: Optional[tuple] = None  # (x0, y0, x1, y1) of the detected bar
    scale_bar_length_px: Optional[float] = None
    label_text: Optional[str] = None

    @property
    def ok(self):
        return self.um_per_px is not None and self.um_per_px > 0


@dataclass
class Pore:
    pore_id: int
    x_px: float
    y_px: float
    diameter_px: float
    area_px: float
    major_px: float
    minor_px: float
    along_px: float  # position along the frustule's long axis, relative to its centroid
    across_px: float


@dataclass
class Frustule:
    frustule_id: int
    bbox: tuple  # (min_row, min_col, max_row, max_col)
    centroid_px: tuple  # (x, y)
    area_px: float
    length_px: float
    width_px: float
    equiv_diameter_px: float
    orientation_deg: Optional[float]
    solidity: float
    rect_fill: float
    ellipse_iou: float
    circularity: float
    notch_depth_ratio: float
    inward_corner_deg: float
    touches_border: bool
    constricted: bool = False  # a waist mirrored on both margins (natural, e.g. capitate apices)
    view: str = "uncertain"
    morphotype: str = "unclassified"
    damage: str = "uncertain"
    crack_length_px: float = 0.0
    crack_candidates: list = field(default_factory=list)
    origin: str = "auto"  # "auto" (detected) or "manual" (added by a click)
    graded_by: str = "tool"  # "tool", or "you" when the condition was set by hand
    species: str = ""  # "" = no species library loaded, "unknown" = no confident match
    species_confidence: float = 0.0
    species_distance: float = float("nan")
    pores: list = field(default_factory=list)
    features: Optional[dict] = None

    @property
    def aspect_ratio(self):
        return self.length_px / self.width_px if self.width_px > 0 else float("nan")


@dataclass
class ImageResult:
    name: str
    image: np.ndarray  # grayscale float in [0, 1], full frame
    analysis_height: int  # rows below this belong to the instrument databar
    calibration: Calibration
    labels: np.ndarray  # instance label image over the analysis region
    frustules: list
    warnings: list = field(default_factory=list)
