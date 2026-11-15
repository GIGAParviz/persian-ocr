from __future__ import annotations

from indra_ocr.pipeline import Line


def tile_bounds(height: int, overlap_ratio: float) -> tuple[int, int]:
    return int(height * (0.5 + overlap_ratio / 2.0)), int(height * (0.5 - overlap_ratio / 2.0))


def line_iou(box1, box2) -> float:
    x_left, y_top = max(box1[0], box2[0]), max(box1[1], box2[1])
    x_right, y_bottom = min(box1[2], box2[2]), min(box1[3], box2[3])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def merge_lines(base_lines: list, extra_lines: list, y_offset: float = 0) -> list[Line]:
    merged = [
        Line(box=list(l.box), text=l.text.strip(), conf=float(getattr(l, "conf", 1.0)))
        for l in base_lines
        if l.text.strip()
    ]
    for l in extra_lines:
        text = l.text.strip()
        if not text:
            continue
        box = [l.box[0], l.box[1] + y_offset, l.box[2], l.box[3] + y_offset]
        conf = float(getattr(l, "conf", 1.0))
        for i, m in enumerate(merged):
            y_ov = min(m.box[3], box[3]) - max(m.box[1], box[1])
            min_h = max(1.0, min(m.box[3] - m.box[1], box[3] - box[1]))
            x_ov = min(m.box[2], box[2]) - max(m.box[0], box[0])
            min_w = max(1.0, min(m.box[2] - m.box[0], box[2] - box[0]))
            if line_iou(m.box, box) > 0.20 or (y_ov / min_h > 0.55 and x_ov / min_w > 0.50):
                if conf > m.conf:
                    merged[i] = Line(box=box, text=text, conf=conf)
                break
        else:
            merged.append(Line(box=box, text=text, conf=conf))
    return merged


def merge_tiles(top_lines: list, bottom_lines: list, bottom_y0: float) -> list[Line]:
    merged = merge_lines(top_lines, bottom_lines, y_offset=bottom_y0)
    merged.sort(key=lambda m: (round(m.box[1] / 30) * 30, -m.box[0]))
    return merged
