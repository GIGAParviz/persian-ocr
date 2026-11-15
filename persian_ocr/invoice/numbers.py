from __future__ import annotations

import re

from ..text.normalize import normalize_digits


_SEPARATORS = ",،٬٫./"
_COMMAS = set(",،٬")
_GROUPED = re.compile(rf"\d{{1,3}}(?:[{re.escape(_SEPARATORS)}]\d{{3}})+")


def _strip_separators(t: str) -> str:
    seps = {ch for ch in t if ch in _SEPARATORS}
    if not seps:
        return t
    digits = re.sub(r"\D", "", t)
    if _GROUPED.fullmatch(t):
        if seps == {"."} and len(digits) < 5:
            return t
        if seps == {"/"} and len(t) <= 6:
            return t
        return digits
    if seps <= _COMMAS:
        return digits
    return t


def parse_number(s: str) -> int | None:
    t = normalize_digits(s or "")
    if re.fullmatch(r"[\s•·.]+", t or "x"):
        t = t.replace("•", "0").replace("·", "0")
    t = _strip_separators(re.sub(r"\s", "", t))
    if not re.fullmatch(r"\d+", t):
        if re.fullmatch(r"[.•·\s]*", s or "") and s and s.strip():
            return 0
        return None
    return int(t)


def digit_edit_distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_close(ocr_value: int, expected: int) -> bool:
    return digit_edit_distance(str(ocr_value), str(expected)) <= 1
