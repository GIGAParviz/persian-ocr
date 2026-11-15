from __future__ import annotations

import re

from ..tables.models import Table
from ..text.correction import correct_by_checksum
from ..text.normalize import normalize_digits
from ..text.validators import is_valid_postal_code
from .numbers import digit_edit_distance

HEADER_FIELDS = [
    ("invoice_date", r"تاریخ\s*:?[\s\S]{0,40}?(1[34]\d{2}\s*/\s*\d{1,2}\s*/\s*\d{1,2})"),
    ("invoice_no", r"(?:شماره\s*سریال|شماره\s*فاکتور|(?:^|\n)\s*شماره)\s*:?[\s\S]{0,25}?(?<![\d/])(\d{2,10})(?![\d/])"),
    ("tax_unique_id", r"(?:شناسه\s*یکتای\s*مالیاتی|شماره\s*منحصر\s*به\s*فرد\s*مالیاتی)\s*:?[\s\S]{0,40}?([A-Z][A-Z0-9]{11,25})"),
]
_ANY_DATE = r"(?<!\d)(1[34]\d{2}\s*/\s*\d{1,2}\s*/\s*\d{1,2})(?!\d)"
PARTY_FIELDS = [
    ("economic_code", r"شماره\s*اقتصادی\s*:?\s*(\d{10,14})"),
    ("national_id", r"شناسه\s*ملی\s*:?\s*(\d{10,12})"),
    ("registration_no", r"شماره\s*ثبت\s*(?:/\s*شماره\s*ملی)?\s*:?\s*(\d{3,11})"),
    ("postal_code", r"کد\s*[پب]ستی\s*:?\s*(\d{9,11})"),
    ("phone", r"(?:شماره\s*)?تلفن\s*:?\s*([\d\-]{8,14})"),
]


def flat_rows(table: Table) -> list[str]:
    return [normalize_digits(" ".join(c.text for c in row if c.text)) for row in table.rows]


def extract_header(rows_flat: list[str], page_text: str) -> dict:
    all_text = " \n ".join(rows_flat) + "\n" + normalize_digits(page_text)
    header = {}
    for key, pattern in HEADER_FIELDS:
        m = re.search(pattern, all_text, flags=re.M)
        if m:
            header[key] = re.sub(r"\s", "", m.group(1))
    if "invoice_date" not in header:
        m = re.search(_ANY_DATE, all_text)
        if m:
            header["invoice_date"] = re.sub(r"\s", "", m.group(1))
    return header


def party_sections(rows: list[str]) -> dict[str, str]:
    eco_rows = [t for t in rows if re.search(r"شماره\s*اقتصادی", t)]
    has_titles = any(re.search(r"فروشنده|خریدار", t) and len(t) < 40 for t in rows)
    if not has_titles and len(eco_rows) >= 2:
        return {"seller": eco_rows[0], "buyer": eco_rows[1]}

    section, buf = None, {"seller": [], "buyer": []}
    for t in rows:
        if re.search(r"فروشنده", t) and len(t) < 40:
            section = "seller"
            continue
        if re.search(r"خریدار", t) and len(t) < 40:
            section = "buyer"
            continue
        if re.search(r"مشخصات\s*کالا|شرح\s*کالا|ردیف", t):
            section = None
        if section:
            buf[section].append(t)
    return {k: " ".join(v) for k, v in buf.items()}


def _validate_id(value: str, kind: str, checks: list, label: str) -> str:
    res = correct_by_checksum(value, kind=kind)
    if res["status"] == "valid":
        checks.append({"check": f"{label}: checksum", "status": "ok"})
    elif res["status"] == "auto_corrected":
        checks.append({"check": f"{label}: checksum", "status": "corrected", "ocr": value, "fixed": res["output"]})
        return res["output"]
    else:
        checks.append({"check": f"{label}: checksum", "status": "mismatch", "ocr": value, "candidates": res.get("candidates", [])})
    return value


def _fix_legal_ids(party: dict, side: str, checks: list) -> None:
    ids11 = [party[k] for k in ("economic_code", "national_id", "registration_no") if k in party and len(party[k]) == 11]
    valid_ids = {v for v in ids11 if correct_by_checksum(v, kind="legal")["status"] == "valid"}
    for key in ("economic_code", "national_id"):
        if key not in party or len(party[key]) != 11:
            continue
        anchor = next((v for v in valid_ids if v != party[key] and digit_edit_distance(v, party[key]) == 1), None)
        if anchor and party[key] not in valid_ids:
            checks.append({"check": f"{side}.{key}: matches legal id", "status": "corrected", "ocr": party[key], "fixed": anchor})
            party[key] = anchor
        else:
            party[key] = _validate_id(party[key], "legal", checks, f"{side}.{key}")


def extract_parties(rows_flat: list[str], checks: list) -> dict[str, dict]:
    parties = {}
    for side, text in party_sections(rows_flat).items():
        party = {}
        for key, pattern in PARTY_FIELDS:
            m = re.search(pattern, text)
            if m:
                party[key] = m.group(1)
        _fix_legal_ids(party, side, checks)
        if "postal_code" in party:
            ok = is_valid_postal_code(party["postal_code"])
            checks.append({"check": f"{side}.postal_code: format", "status": "ok" if ok else "mismatch", "ocr": party["postal_code"]})
        parties[side] = party
    return parties
