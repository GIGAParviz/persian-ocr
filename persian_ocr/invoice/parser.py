from __future__ import annotations

import re

from ..tables.models import Table
from ..text.normalize import normalize_digits
from .columns import NUMERIC_ROLES, assign_cells, find_item_header
from .equations import VAT_RATES, reconcile, reconcile_by_rate, sum_check, summarize, vat, verify_item
from .header import extract_header, extract_parties, flat_rows
from .numbers import parse_number

TOTAL_LABELS = [
    ("total", r"جمع\s*کل|جمع\s*[كک]ل|^جمع$"),
    ("discount_total", r"تخفیفات"),
    ("freight", r"کرایه"),
    ("vat", r"ارزش\s*افزوده|مالیات"),
    ("payable", r"قابل\s*پرداخت(?!\s*به\s*حروف)"),
]


def _parse_items(table: Table, header_idx: int, col_boxes: dict, rows_flat: list[str], checks: list) -> tuple[list[dict], int | None]:
    items: list[dict] = []
    for ri in range(header_idx + 1, len(table.rows)):
        if re.search(r"جمع", rows_flat[ri]):
            return items, ri
        cells = assign_cells(table.rows[ri], col_boxes)
        numbers = {k: parse_number(v) for k, v in cells.items() if k in NUMERIC_ROLES}
        numbers = {k: v for k, v in numbers.items() if v is not None}
        if not numbers.get("amount") and not numbers.get("unit_price") and not numbers.get("net"):
            continue
        item = {"description": cells.get("description", ""), "code": cells.get("code", ""), "unit": cells.get("unit", ""), **numbers}
        verify_item(item, checks, len(items) + 1)
        items.append(item)
    return items, None


def _parse_totals(table: Table, totals_row: int, col_boxes: dict) -> dict[str, int]:
    totals: dict[str, int] = {}
    for k, v in assign_cells(table.rows[totals_row], col_boxes).items():
        n = parse_number(v)
        if k in NUMERIC_ROLES and n is not None:
            totals[f"sum_{k}"] = n
    has_col_sums = any(k.startswith("sum_") for k in totals)
    for ri in range(totals_row, len(table.rows)):
        row = table.rows[ri]
        for c in row:
            for key, pattern in TOTAL_LABELS:
                if key == "total" and has_col_sums:
                    continue
                if c.text and re.search(pattern, normalize_digits(c.text)) and key not in totals:
                    nums = [parse_number(o.text) for o in row if o is not c and o.text]
                    nums = [n for n in nums if n is not None and n >= 1000]
                    if nums:
                        totals[key] = max(nums)
    return totals


def _check_totals(items: list[dict], totals: dict, checks: list) -> None:
    for col in ("amount", "after_discount", "tax", "net"):
        values = [it[col] for it in items if col in it]
        if values and len(values) == len(items) and f"sum_{col}" in totals:
            sum_check(totals, f"sum_{col}", col, sum(values), checks)
    if "total" in totals and items and all("amount" in it for it in items):
        sum_check(totals, "total", "amount", sum(it["amount"] for it in items), checks)
    if "total" in totals and "vat" in totals:
        base = totals["total"] - totals.get("discount_total", 0) + totals.get("freight", 0)
        reconcile_by_rate(totals, "vat", {p: vat(base, p) for p in VAT_RATES}, checks, lambda p: f"vat={p}%")
        if "payable" in totals:
            reconcile(totals, "payable", base + totals["vat"], checks, "total+vat=payable")


def parse_invoice(table: Table, page_text: str = "") -> dict | None:
    found = find_item_header(table)
    if found is None:
        return None
    header_idx, col_boxes = found
    checks: list[dict] = []
    rows_flat = flat_rows(table)

    items, totals_row = _parse_items(table, header_idx, col_boxes, rows_flat, checks)
    totals = _parse_totals(table, totals_row, col_boxes) if totals_row is not None else {}
    _check_totals(items, totals, checks)

    header = extract_header(rows_flat, page_text)
    parties = extract_parties(rows_flat, checks)
    return {"header": header, "parties": parties, "items": items, "totals": totals, "checks": checks, "check_summary": summarize(checks)}
