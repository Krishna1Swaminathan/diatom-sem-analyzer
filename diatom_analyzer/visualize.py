"""Annotated overlay: outlines coloured by damage, IDs, long axes, pores and the scale bar."""

import math

import cv2
import numpy as np

DAMAGE_COLORS = {  # RGB status colours; always paired with a text label, never colour alone
    "intact": (12, 163, 12),
    "cracked": (250, 178, 25),
    "fragmented": (208, 59, 59),
    "uncertain": (170, 170, 170),
}
PORE_COLOR = (86, 180, 233)
BAR_COLOR = (204, 121, 167)


def render_overlay(result, show_pores=True, show_axes=True):
    img = np.clip(result.image * 255, 0, 255).astype(np.uint8)
    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    h, w = img.shape
    thick = max(2, int(round(w / 500)))
    font_scale = max(0.5, w / 1400)

    if result.analysis_height < h:
        cv2.line(rgb, (0, result.analysis_height), (w, result.analysis_height), BAR_COLOR, 1)

    for fr in result.frustules:
        color = DAMAGE_COLORS.get(fr.damage, DAMAGE_COLORS["uncertain"])
        r0, c0, r1, c1 = fr.bbox
        mask = (result.labels[r0:r1, c0:c1] == fr.frustule_id).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(rgb, contours, -1, color, thick, offset=(c0, r0), lineType=cv2.LINE_AA)

        if show_pores:
            for p in fr.pores:
                cv2.circle(rgb, (int(round(p.x_px)), int(round(p.y_px))), max(1, int(round(p.diameter_px / 2))),
                           PORE_COLOR, 1, lineType=cv2.LINE_AA)

        cx, cy = fr.centroid_px
        if show_axes and fr.orientation_deg is not None:
            t = math.radians(fr.orientation_deg)
            dx, dy = math.cos(t) * fr.length_px / 2, -math.sin(t) * fr.length_px / 2
            cv2.line(rgb, (int(cx - dx), int(cy - dy)), (int(cx + dx), int(cy + dy)), (255, 255, 255),
                     max(1, thick - 1), lineType=cv2.LINE_AA)

        label = str(fr.frustule_id)
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
        x, y = int(cx - tw / 2), int(cy + th / 2)
        cv2.rectangle(rgb, (x - 4, y - th - 4), (x + tw + 4, y + base + 2), (0, 0, 0), -1)
        cv2.putText(rgb, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thick, cv2.LINE_AA)

    bbox = result.calibration.scale_bar_bbox
    if bbox:
        x0, y0, x1, y1 = bbox
        cv2.rectangle(rgb, (x0 - 3, y0 - 3), (x1 + 3, y1 + 3), BAR_COLOR, max(1, thick - 1))
    return rgb


def legend_items():
    return [(name, "#%02x%02x%02x" % color) for name, color in DAMAGE_COLORS.items()]
