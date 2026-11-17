from __future__ import annotations

import re

import cv2
import numpy as np
from indra_ocr.pipeline import Line
from indra_ocr.rtl import flip

from persian_ocr.text import normalize, normalize_digits


def _center(line: Line) -> float:
    return (line.box[1] + line.box[3]) / 2


def _number(text: str) -> int | None:
    matches = re.findall(r"\d[\d,،٬.]*", normalize_digits(normalize(text)))
    if len(matches) != 1:
        return None
    digits = re.sub(r"\D", "", matches[0])
    return int(digits) if 4 <= len(digits) <= 12 else None


def _read_number(engine, gray: np.ndarray, box: list[int], methods: tuple[str, ...]) -> tuple[int, float] | None:
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return None
    sx0, sy0 = max(0, x0 - 120), max(0, y0 - 120)
    sx1, sy1 = min(gray.shape[1], x1 + 120), min(gray.shape[0], y1 + 120)
    tile = gray[sy0:sy1, sx0:sx1]
    local_box = np.array([[x0 - sx0, y0 - sy0, x1 - sx0, y1 - sy0, 1.0]], dtype=np.float32)
    readings = []
    for method in methods:
        if method == "original":
            image = tile
        elif method == "highpass":
            blurred = cv2.GaussianBlur(tile, (0, 0), 31)
            image = np.clip((tile.astype(np.float32) - blurred.astype(np.float32)) * 2 + 220, 0, 255).astype(np.uint8)
        else:
            image = cv2.adaptiveThreshold(tile, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
        text, confidence, _ = engine.ort.recognize(image, local_box)[0]
        normalized = normalize_digits(flip(text)).strip()
        if float(confidence) < 0.5 or not re.fullmatch(r"[\d,،٬\s]+", normalized):
            return None
        digits = re.sub(r"\D", "", normalized)
        if not 5 <= len(digits) <= 12:
            return None
        readings.append((int(digits), float(confidence)))
    if len({value for value, _ in readings}) != 1:
        return None
    return readings[0][0], min(confidence for _, confidence in readings)


def _row(lines: list[Line], label: Line) -> list[Line]:
    height = label.box[3] - label.box[1]
    return [line for line in lines if line is not label and abs(_center(line) - _center(label)) <= height * 0.4 and line.box[2] < label.box[0] + height * 0.1]


def _number_box(label: Line, row: list[Line], right_ratio: float, bottom_trim: int) -> list[int] | None:
    numeric = [line for line in row if any(char.isdigit() for char in line.text)]
    if not numeric:
        return None
    height = label.box[3] - label.box[1]
    return [
        round(min(line.box[0] for line in numeric)) - 2,
        round(min([label.box[1]] + [line.box[1] for line in numeric])) - 1,
        round(label.box[0] + height * right_ratio),
        round(max([label.box[3]] + [line.box[3] for line in numeric])) - bottom_trim,
    ]


def recover_faint_payable(engine, gray: np.ndarray, lines: list[Line]) -> tuple[list[Line], list[dict]]:
    for payable in lines:
        name = normalize(payable.text)
        if not re.search(r"قابل\s+[بپ]رداخت", name) or _number(payable.text) is not None:
            continue
        height = payable.box[3] - payable.box[1]
        payable_row = _row(lines, payable)
        if any(_number(line.text) is not None for line in payable_row):
            continue
        paid = next((line for line in lines if re.search(r"پرداخت\s+شده", normalize(line.text)) and 0 < _center(line) - _center(payable) <= height * 1.8), None)
        if paid is None or _number(paid.text) is not None:
            continue
        paid_row = _row(lines, paid)
        payable_box = _number_box(payable, payable_row, 0.38, 3)
        paid_box = _number_box(paid, paid_row, 0.85, 1)
        if payable_box is None or paid_box is None:
            continue
        total = next((_number(line.text) for line in lines if "مجموع" in normalize(line.text) and 0 < _center(payable) - _center(line) <= height * 2 and _number(line.text) is not None), None)
        discount = next((_number(line.text) for line in lines if "تخفیف" in normalize(line.text) and 0 < _center(payable) - _center(line) <= height * 2 and _number(line.text) is not None), None)
        if total is None or discount is None or total <= discount:
            continue
        payable_read = _read_number(engine, gray, payable_box, ("highpass", "adaptive"))
        paid_read = _read_number(engine, gray, paid_box, ("original", "highpass", "adaptive"))
        if payable_read is None or paid_read is None or payable_read[0] != paid_read[0]:
            continue
        value = payable_read[0]
        if abs(value - (total - discount)) > 1000:
            continue
        amount = f"{value:,}"
        payable_text = f"قابل پرداخت: {amount}"
        paid_text = f"پرداخت شده: {amount}"
        removed = {id(line) for line in [payable, paid, *payable_row, *paid_row]}
        recovered = [line for line in lines if id(line) not in removed]
        for label, row, text, confidence in ((payable, payable_row, payable_text, payable_read[1]), (paid, paid_row, paid_text, paid_read[1])):
            members = [label, *row]
            recovered.append(Line(box=[min(line.box[0] for line in members), min(line.box[1] for line in members), max(line.box[2] for line in members), max(line.box[3] for line in members)], text=text, conf=min(float(label.conf), confidence)))
        recovered.sort(key=lambda line: (round(line.box[1] / 30) * 30, -line.box[0]))
        review = [{
            "kind": "faint_payable_reread",
            "input": f"{payable.text} | {paid.text}",
            "output": payable_text,
            "status": "ambiguous_review",
            "candidates": [amount],
            "note": "payable_paid_and_total_discount_agree",
            "total": total,
            "discount": discount,
            "payable_conf": round(payable_read[1], 3),
            "paid_conf": round(paid_read[1], 3),
        }]
        return recovered, review
    return lines, []
