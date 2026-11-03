"""Coordinate helpers: normalized boxes -> original pixel boxes, IoU."""

from __future__ import annotations

from dataclasses import dataclass


def denormalize_box(box, width: int, height: int, fmt: str) -> list[int]:
    """Convert one box to original pixel coords [x1, y1, x2, y2] (ints).

    Args:
        box: [x1, y1, x2, y2] in the given format.
        width, height: original image size in pixels.
        fmt: "pixel" | "norm1000" | "norm01".
    """
    if fmt not in ("pixel", "norm1000", "norm01"):
        raise ValueError(f"unknown coord format: {fmt}")
    x1, y1, x2, y2 = (float(v) for v in box)
    if fmt == "norm1000":
        x1 = x1 / 1000.0 * width
        x2 = x2 / 1000.0 * width
        y1 = y1 / 1000.0 * height
        y2 = y2 / 1000.0 * height
    elif fmt == "norm01":
        x1 = x1 * width
        x2 = x2 * width
        y1 = y1 * height
        y2 = y2 * height
    # Clip and order. x2/y2 are exclusive bounds (width = x2 - x1).
    ix1 = max(0, min(int(round(x1)), width))
    iy1 = max(0, min(int(round(y1)), height))
    ix2 = max(0, min(int(round(x2)), width))
    iy2 = max(0, min(int(round(y2)), height))
    if ix2 < ix1:
        ix1, ix2 = ix2, ix1
    if iy2 < iy1:
        iy1, iy2 = iy2, iy1
    return [ix1, iy1, ix2, iy2]


def box_area(box) -> int:
    x1, y1, x2, y2 = box
    return max(0, int(x2) - int(x1)) * max(0, int(y2) - int(y1))


def box_iou(a, b) -> float:
    """Intersection over union for [x1, y1, x2, y2] boxes (exclusive bounds)."""
    ax1, ay1, ax2, ay2 = (int(v) for v in a)
    bx1, by1, bx2, by2 = (int(v) for v in b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    union = box_area(a) + box_area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def mean_best_iou(pred_boxes, truth_boxes) -> float:
    """Mean over predictions of max IoU against any truth box."""
    if not pred_boxes:
        return 0.0
    if not truth_boxes:
        return 0.0
    total = 0.0
    for p in pred_boxes:
        total += max(box_iou(p, t) for t in truth_boxes)
    return total / len(pred_boxes)


# -- Box with coordinate system (M0-fix1 C14) -------------------------------
# Spark reading boxes are "norm1000" (0-1000 per axis, M0 review).
# SAM boxes are "pixel" in the input size SAM was told (M0 review: the
# prompt carries w/h, e.g. 640x960 for chat_capture.png, 360x400 for
# chat_scroll.mp4 frame 0; SAM returns pixel coords in that space).
# ref_w/ref_h always mean "size of the image the box was predicted on".
# For norm1000 the values are provenance only (conversion scales 0-1000
# to the target size); for pixel they are the scale source.


@dataclass(frozen=True)
class Box:
    """A box bundled with its coordinate system.

    Attributes:
        x1, y1, x2, y2: coordinates in ``system`` units.
        system: "norm1000" (Spark) or "pixel" (SAM).
        ref_w, ref_h: prediction-image size in pixels.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    system: str
    ref_w: int
    ref_h: int

    def __post_init__(self) -> None:
        if self.system not in ("norm1000", "pixel"):
            raise ValueError(f"unknown box system: {self.system!r}")
        if int(self.ref_w) <= 0 or int(self.ref_h) <= 0:
            raise ValueError(
                f"ref size must be positive: {self.ref_w}x{self.ref_h}"
            )


def box_to_pixels(box: Box, width: int, height: int) -> list[int]:
    """Convert a Box to original pixel coords [x1, y1, x2, y2] (ints).

    Args:
        box: the box with its coordinate system.
        width, height: original (target) image size in pixels.

    For "norm1000", scales 0-1000 to the target size (ref is provenance).
    For "pixel", scales from ref_w/ref_h to the target size (identity when
    the SAM input size equals the original, as in M0).
    """
    if box.system == "norm1000":
        return denormalize_box(
            [box.x1, box.y1, box.x2, box.y2], int(width), int(height),
            "norm1000",
        )
    if box.system == "pixel":
        # Scale from prediction space to target space, then clip/order.
        sx = int(width) / float(int(box.ref_w))
        sy = int(height) / float(int(box.ref_h))
        scaled = [float(box.x1) * sx, float(box.y1) * sy,
                  float(box.x2) * sx, float(box.y2) * sy]
        return denormalize_box(scaled, int(width), int(height), "pixel")
    raise ValueError(f"unknown box system: {box.system!r}")


def box_iou_boxes(a: Box, b: Box) -> float:
    """IoU for two Boxes in the same coordinate space.

    Raises ValueError when the boxes use different systems or different
    reference sizes: convert both with box_to_pixels() to a common
    original size first, then use box_iou() on the pixel results.
    """
    if a.system != b.system:
        raise ValueError(
            f"cannot mix coordinate systems: {a.system!r} vs {b.system!r} "
            "(convert both with box_to_pixels first)"
        )
    if int(a.ref_w) != int(b.ref_w) or int(a.ref_h) != int(b.ref_h):
        raise ValueError(
            f"cannot mix reference sizes: {a.ref_w}x{a.ref_h} vs "
            f"{b.ref_w}x{b.ref_h} (convert both with box_to_pixels first)"
        )
    pa = box_to_pixels(a, int(a.ref_w), int(a.ref_h))
    pb = box_to_pixels(b, int(b.ref_w), int(b.ref_h))
    return box_iou(pa, pb)
