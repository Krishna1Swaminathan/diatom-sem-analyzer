"""Grade each frustule as intact, cracked or fragmented.

Rules, in order (all thresholds live in DamageConfig and are exported with the results):
  * touching the frame edge                       -> "uncertain" (outline is cut by the frame)
  * outline far from a regular shape               -> "fragmented"
    (solidity below fragmented_solidity, neither ellipse- nor rectangle-like, or a bite out
    of the outline deeper than fragmented_notch_ratio of the width)
  * long thin dark line across the shell, a notch
    in the outline, or mildly concave outline      -> "cracked"
  * otherwise                                     -> "intact"

When the frustule confidently matches a species in the reference library, the outline tests
are made relative to that species' own typical outline, so naturally irregular species
(crescent-shaped, triangular...) are not mistaken for fragments.
"""

from .config import DamageConfig


def crack_length(crack_candidates, cfg):
    # Many parallel long dark lines are striae (rows of pores), not cracks.
    if not crack_candidates or len(crack_candidates) > cfg.max_crack_candidates:
        return 0.0
    return max(crack_candidates)


def grade_damage(fr, crack_candidates, cfg=None, reference=None):
    cfg = cfg or DamageConfig()
    fr.crack_length_px = crack_length(crack_candidates, cfg)
    if fr.touches_border:
        return "uncertain"

    frag_regularity = cfg.fragmented_regularity
    frag_solidity = cfg.fragmented_solidity
    crack_solidity = cfg.cracked_solidity
    if reference:
        ref_regularity = max(reference.get("ellipse_iou", 1.0), reference.get("rect_fill", 1.0))
        ref_solidity = reference.get("solidity", 1.0)
        frag_regularity = min(frag_regularity, ref_regularity - 0.08)
        frag_solidity = min(frag_solidity, ref_solidity - 0.08)
        crack_solidity = min(crack_solidity, ref_solidity - 0.03)

    regularity = max(fr.ellipse_iou, fr.rect_fill)
    if (fr.solidity < frag_solidity or regularity < frag_regularity
            or fr.notch_depth_ratio > cfg.fragmented_notch_ratio):
        return "fragmented"
    if (fr.crack_length_px >= cfg.crack_length_ratio * fr.length_px
            or fr.notch_depth_ratio > cfg.notch_depth_ratio
            or fr.solidity < crack_solidity):
        return "cracked"
    return "intact"
