from __future__ import annotations

from typing import Callable

from .numbers import is_close

VAT_RATES = (10, 9)
CHECK_STATUSES = ("ok", "corrected", "filled", "mismatch", "deferred")


def reconcile(values: dict, key: str, expected: int, checks: list, label: str) -> None:
    got = values.get(key)
    if got is None:
        values[key] = expected
        checks.append({"check": label, "status": "filled", "expected": expected})
    elif got == expected:
        checks.append({"check": label, "status": "ok"})
    elif is_close(got, expected):
        values[key] = expected
        checks.append({"check": label, "status": "corrected", "ocr": got, "fixed": expected})
    else:
        checks.append({"check": label, "status": "mismatch", "ocr": got, "expected": expected})


def sum_check(totals: dict, key: str, col: str, page_sum: int, checks: list) -> None:
    got = totals[key]
    label = f"sum({col})={key}"
    if got == page_sum:
        checks.append({"check": label, "status": "ok"})
    elif is_close(got, page_sum):
        totals[key] = page_sum
        checks.append({"check": label, "status": "corrected", "ocr": got, "fixed": page_sum})
    else:
        checks.append({"check": label, "status": "deferred", "key": key, "col": col, "ocr": got, "page_sum": page_sum})


def summarize(checks: list) -> dict:
    return {s: sum(1 for c in checks if c["status"] == s) for s in CHECK_STATUSES}


def vat(base: int, pct: int) -> int:
    return (base * pct + 50) // 100


def reconcile_by_rate(values: dict, key: str, expected_by_pct: dict[int, int], checks: list, label: Callable[[str], str]) -> bool:
    got = values[key]
    for pct, expected in expected_by_pct.items():
        if got == expected:
            reconcile(values, key, expected, checks, label(str(pct)))
            return True
    close: dict[int, int] = {}
    for pct, expected in expected_by_pct.items():
        if is_close(got, expected):
            close.setdefault(expected, pct)
    if len(close) == 1:
        expected, pct = next(iter(close.items()))
        reconcile(values, key, expected, checks, label(str(pct)))
        return True
    if len(close) > 1:
        checks.append({"check": label("|".join(str(p) for p in close.values())), "status": "mismatch", "ocr": got, "candidates": sorted(close)})
        return True
    return False


def _downstream_support(vals: dict, amount: int) -> int:
    base = amount - (vals.get("discount") or 0) + (vals.get("additions") or 0)
    after, tax, net = vals.get("after_discount"), vals.get("tax"), vals.get("net")
    score = 0
    if after is not None:
        score += after == base
    if tax is not None:
        score += any(tax == vat(base, p) for p in VAT_RATES)
    if net is not None:
        score += net == base + tax if tax is not None else any(net == base + vat(base, p) for p in VAT_RATES)
    return score


def _verify_qty_unit_amount(vals: dict, checks: list, label: str) -> None:
    q, u, a = vals["qty"], vals["unit_price"], vals["amount"]
    if q * u == a:
        checks.append({"check": label, "status": "ok"})
        return
    options: list[tuple[str, int, int]] = []
    if is_close(a, q * u):
        options.append(("amount", q * u, q * u))
    if a % q == 0 and is_close(u, a // q):
        options.append(("unit_price", a // q, a))
    if u and a % u == 0 and is_close(q, a // u):
        options.append(("qty", a // u, a))
    if len(options) > 1:
        scores = [_downstream_support(vals, amount) for _, _, amount in options]
        options = [o for o, s in zip(options, scores) if s == max(scores)]
    if len(options) == 1:
        key, value, _ = options[0]
        reconcile(vals, key, value, checks, label)
        return
    entry = {"check": label, "status": "mismatch", "ocr": [q, u, a]}
    if options:
        entry["candidates"] = [{key: value} for key, value, _ in options]
    checks.append(entry)


def verify_item(vals: dict, checks: list, row_idx: int) -> None:
    q, u, a = vals.get("qty"), vals.get("unit_price"), vals.get("amount")
    if q and u is not None and a is not None:
        _verify_qty_unit_amount(vals, checks, f"row{row_idx}: qty*unit=amount")

    a = vals.get("amount")
    discount, additions = vals.get("discount") or 0, vals.get("additions") or 0
    if a is not None and "after_discount" in vals:
        reconcile(vals, "after_discount", a - discount + additions, checks, f"row{row_idx}: amount-discount+add=after")

    base = vals.get("after_discount", vals.get("amount"))
    if base and vals.get("tax") is not None:
        reconcile_by_rate(vals, "tax", {p: vat(base, p) for p in VAT_RATES}, checks, lambda p: f"row{row_idx}: tax={p}%")
    net, tax = vals.get("net"), vals.get("tax")
    if base is None or net is None:
        return
    if tax is not None:
        reconcile(vals, "net", base + tax, checks, f"row{row_idx}: base+tax=net")
        return
    expected = {p: base + vat(base, p) for p in VAT_RATES}
    if not reconcile_by_rate(vals, "net", expected, checks, lambda p: f"row{row_idx}: base*(1+{p}%)=net"):
        checks.append({"check": f"row{row_idx}: base*(1+vat)=net", "status": "mismatch", "ocr": [base, net]})
