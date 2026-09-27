"""Grade each frustule as intact, cracked or fragmented.

Rules, in order (all thresholds live in DamageConfig and are exported with the results):
  * touching the frame edge                          -> "uncertain" (outline is cut by the frame)
  * a sharp inward corner in the outline, very low
    solidity, or a deep bite out of the margin         -> "fragmented"
  * a long thin dark line across the shell, or a
    smaller sharp corner (a chip)                      -> "cracked"
  * otherwise                                        -> "intact"

Intact valves have smooth outlines, even when concave (crescent-shaped species) or angular
(triangular centrics, whose corners are rounded and point outwards). Fractures meet the natural
margin at sharp re-entrant corners, which is what the corner test measures.

A waist mirrored on both margins (capitate or constricted species, such as Didymosphenia) is
natural: its corners are not counted and the solidity and notch limits are relaxed for it.

When the frustule confidently matches a species in the reference library whose outline is
naturally concave, the solidity threshold is relaxed to that species' own typical value. The
library only ever relaxes the rules, so a wrong species guess cannot make a frustule "broken".
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

    frag_solidity, notch_ratio = cfg.fragmented_solidity, cfg.fragmented_notch_ratio
    if reference and "solidity" in reference:
        frag_solidity = min(frag_solidity, reference["solidity"] - 0.08)
    if fr.constricted:  # a natural waist lowers solidity and is itself a notch
        frag_solidity = min(frag_solidity, cfg.constricted_solidity)
        notch_ratio = max(notch_ratio, cfg.constricted_notch_ratio)

    if (fr.inward_corner_deg >= cfg.fragment_corner_deg or fr.solidity < frag_solidity
            or fr.notch_depth_ratio > notch_ratio):
        return "fragmented"
    if fr.crack_length_px >= cfg.crack_length_ratio * fr.length_px or fr.inward_corner_deg >= cfg.chip_corner_deg:
        return "cracked"
    return "intact"
