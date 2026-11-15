from __future__ import annotations

import re

from .normalize import normalize_digits


def is_valid_nid(nid10: str) -> bool:
    d = normalize_digits(nid10).strip()
    if not re.fullmatch(r"\d{10}", d) or len(set(d)) == 1:
        return False
    digits = [int(c) for c in d]
    r = sum(digits[i] * (10 - i) for i in range(9)) % 11
    return digits[9] == r if r < 2 else digits[9] == 11 - r


def is_valid_legal_id(legal11: str) -> bool:
    d = normalize_digits(legal11).strip()
    if not re.fullmatch(r"\d{11}", d):
        return False
    digits = [int(c) for c in d]
    tens_plus_2 = digits[9] + 2
    weights = [29, 27, 23, 19, 17, 29, 27, 23, 19, 17]
    r = sum((digits[i] + tens_plus_2) * weights[i] for i in range(10)) % 11 % 10
    return digits[10] == r


def is_valid_ir_iban(iban: str) -> bool:
    s = normalize_digits(iban).strip().upper().replace(" ", "-").replace("-", "").replace("IR", "")
    if not re.fullmatch(r"\d{24}", s):
        return False
    rem = 0
    for ch in s[2:] + "1827" + s[:2]:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1


def is_valid_postal_code(code: str) -> bool:
    return bool(re.fullmatch(r"[1-9]\d{9}", normalize_digits(code).strip()))
