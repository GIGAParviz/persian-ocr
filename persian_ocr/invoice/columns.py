from __future__ import annotations

import re

from ..tables.models import BBox, Table
from ..text.normalize import normalize_digits

COLUMN_ROLES = [
    ("after_discount", r"پس\s*از"),
    ("net", r"خالص|قابل\s*پرداخت|بعلاوه|به\s*علاوه|جمع\s*مبلغ\s*کل"),
    ("tax", r"مالیات|عوارض|ارزش\s*افزوده"),
    ("discount", r"تخفیف"),
    ("additions", r"اضافات"),
    ("unit_price", r"مبلغ\s*واحد|^\s*فی\s*$|فی\s*واحد"),
    ("amount", r"مبلغ\s*کل|^\s*مبلغ\s*$|مبلغ\s*[كک]ل"),
    ("qty", r"مقدار|تعداد"),
    ("unit", r"^\s*واحد\s*$|واحد\s*اندازه"),
    ("description", r"شرح"),
    ("code", r"کد\s*کالا|شناسه\s*کالا|کد"),
    ("row_no", r"ردیف"),
]
NUMERIC_ROLES = {"qty", "unit_price", "amount", "discount", "additions", "after_discount", "tax", "net"}


def role_of(text: str) -> str | None:
    t = normalize_digits(text)
    for role, pattern in COLUMN_ROLES:
        if re.search(pattern, t):
            return role
    return None


def x_overlap(a: BBox, b: BBox) -> float:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) / max(1, min(a[2] - a[0], b[2] - b[0]))


def find_item_header(table: Table) -> tuple[int, dict[str, BBox]] | None:
    best = None
    for ri, row in enumerate(table.rows):
        roles: dict[str, BBox] = {}
        for c in row:
            r = role_of(c.text)
            if r and r not in roles:
                roles[r] = c.box
        n_numeric = len(set(roles) & NUMERIC_ROLES)
        if n_numeric >= 3 and (best is None or n_numeric > best[2]):
            best = (ri, roles, n_numeric)
    return (best[0], best[1]) if best else None


def assign_cells(row, col_boxes: dict[str, BBox]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in row:
        if not c.text:
            continue
        best_role, best_ov = None, 0.5
        for role, header_box in col_boxes.items():
            ov = x_overlap(c.box, header_box)
            if ov > best_ov:
                best_role, best_ov = role, ov
        if best_role:
            out[best_role] = (out.get(best_role, "") + " " + c.text).strip()
    return out
