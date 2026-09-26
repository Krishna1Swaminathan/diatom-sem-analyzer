from dataclasses import asdict, dataclass, field


@dataclass
class SegmentationConfig:
    method: str = "classical"  # "classical" or "cellpose"
    min_frustule_um: float = 3.0  # objects with equivalent diameter below this are ignored
    split_touching: bool = True
    split_prominence: float = 0.35  # h-maxima height as a fraction of the component's max distance
    edge_pore_close_um: float = 0.4  # gaps up to about this size in the outline are closed


@dataclass
class PoreConfig:
    min_diameter_um: float = 0.03
    max_diameter_um: float = 4.0
    max_fraction_of_width: float = 0.25  # dark regions wider than this share of the frustule are not pores
    contrast_k: float = 0.5  # how far below the local shell brightness (in local std units) a pore must be
    min_area_px: int = 4


@dataclass
class DamageConfig:
    fragmented_solidity: float = 0.85
    fragmented_regularity: float = 0.88  # best of ellipse-fit and rectangle-fill
    fragmented_notch_ratio: float = 0.25
    cracked_solidity: float = 0.93
    notch_depth_ratio: float = 0.08
    crack_length_ratio: float = 0.20
    max_crack_candidates: int = 3  # more parallel long dark lines than this are striae, not cracks


@dataclass
class ViewConfig:
    girdle_rect_fill: float = 0.88
    valve_rect_fill: float = 0.85
    round_aspect: float = 1.15


@dataclass
class ClassifierConfig:
    unknown_distance: float = 3.0  # standardized feature distance beyond which a frustule is "unknown"
    k: int = 3


@dataclass
class AnalysisConfig:
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)
    pores: PoreConfig = field(default_factory=PoreConfig)
    damage: DamageConfig = field(default_factory=DamageConfig)
    view: ViewConfig = field(default_factory=ViewConfig)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)

    def to_flat_dict(self):
        flat = {}
        for section, values in asdict(self).items():
            for key, value in values.items():
                flat[f"{section}.{key}"] = value
        return flat
