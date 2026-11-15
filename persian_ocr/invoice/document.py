from __future__ import annotations

from collections import Counter

from .equations import summarize
from .numbers import is_close

_SCALED_COLS = ("unit_price", "amount", "after_discount", "tax", "net")
_HEADER_KEYS = ("invoice_date", "invoice_no", "tax_unique_id")


def _vote_headers(invoices: list[dict]) -> None:
    if len(invoices) < 3:
        return
    for key in _HEADER_KEYS:
        values = [inv["header"].get(key) for inv in invoices if inv["header"].get(key)]
        if len(values) < 3:
            continue
        top, n = Counter(values).most_common(1)[0]
        if n / len(values) < 0.6:
            continue
        for inv in invoices:
            old = inv["header"].get(key)
            if old != top:
                inv["header"][key] = top
                inv["checks"].append({"check": f"header.{key}: page vote", "status": "corrected", "ocr": old, "fixed": top})


def _repair_row_scale(invoices: list[dict]) -> None:
    deferred = {c["col"]: c["ocr"] for inv in invoices for c in inv["checks"] if c["status"] == "deferred"}
    items = [(inv, it) for inv in invoices for it in inv["items"]]
    for col in ("net", "amount", "after_discount", "tax"):
        target = deferred.get(col)
        if target is None or not items or not all(isinstance(it.get(col), int) for _, it in items):
            continue
        total = sum(it[col] for _, it in items)
        if total == target:
            continue
        fixes = [
            (inv, it, f)
            for inv, it in items
            for f in (10, 0.1)
            if round(it[col] * f) != it[col] and total - it[col] + round(it[col] * f) == target
        ]
        if len(fixes) != 1:
            continue
        inv, it, f = fixes[0]
        before = {k: it[k] for k in _SCALED_COLS if isinstance(it.get(k), int)}
        for k, v in before.items():
            it[k] = round(v * f)
        inv["checks"].append({"check": f"document: row scale repair via sum({col})", "status": "corrected",
                              "ocr": before, "fixed": {k: it[k] for k in before}, "factor": f})
        return


def reconcile_document(invoices: list[dict]) -> None:
    if not invoices:
        return
    _vote_headers(invoices)
    _repair_row_scale(invoices)
    doc_sums: dict[str, int] = {}
    for col in ("amount", "after_discount", "tax", "net"):
        values = [it.get(col) for inv in invoices for it in inv["items"]]
        if values and all(isinstance(v, int) for v in values):
            doc_sums[col] = sum(values)
    for inv in invoices:
        for c in inv["checks"]:
            if c["status"] != "deferred":
                continue
            expected = doc_sums.get(c["col"])
            if expected is None or len(invoices) == 1:
                c["status"] = "mismatch"
            elif c["ocr"] == expected:
                c.update(status="ok", scope="document")
            elif is_close(c["ocr"], expected):
                inv["totals"][c["key"]] = expected
                c.update(status="corrected", fixed=expected, scope="document")
            else:
                c.update(status="mismatch", expected_document=expected)
        inv["check_summary"] = summarize(inv["checks"])
