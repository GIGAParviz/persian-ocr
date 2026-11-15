from __future__ import annotations

from .normalize import normalize_digits
from .validators import is_valid_ir_iban, is_valid_legal_id, is_valid_nid

CONFUSION_PAIRS = [("4", "6"), ("4", "2"), ("4", "9"), ("4", "1"), ("6", "9"), ("2", "0"), ("2", "3"), ("5", "7"), ("5", "8"), ("8", "0"), ("8", "3")]


def _symmetric(pairs: list[tuple[str, str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for a, b in pairs:
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


CONFUSION_MAP = _symmetric(CONFUSION_PAIRS)

_CHECKERS = {
    "nid": (10, is_valid_nid),
    "legal": (11, is_valid_legal_id),
    "iban": (24, is_valid_ir_iban),
}


def variants_confusion(s: str) -> list[str]:
    return list(dict.fromkeys(s[:i] + alt + s[i + 1:] for i, ch in enumerate(s) for alt in sorted(CONFUSION_MAP.get(ch, set()))))


def variants_dup_insert(s: str) -> list[str]:
    return list(dict.fromkeys(s[:i] + ch + s[i:] for i, ch in enumerate(s)))


def variants_dup_delete(s: str) -> list[str]:
    return list(dict.fromkeys(s[:i] + s[i + 1:] for i in range(len(s) - 1) if s[i] == s[i + 1]))


def _result(c: str, output: str, status: str, candidates: list[str], note: str | None = None) -> dict:
    res = {"input": c, "output": output, "status": status, "candidates": candidates}
    if note:
        res["note"] = note
    return res


def correct_by_checksum(candidate: str, kind: str) -> dict:
    c = normalize_digits(candidate).strip()
    if kind not in _CHECKERS:
        return _result(c, c, "unknown_kind", [])
    req_len, is_valid = _CHECKERS[kind]
    digits = c.upper().replace("IR", "").replace(" ", "").replace("-", "") if kind == "iban" else c
    personal = kind in ("nid", "legal")

    if personal and len(digits) == req_len - 1:
        cands = [v for v in variants_dup_insert(digits) if is_valid(v)]
        if len(cands) == 1:
            return _result(c, cands[0], "auto_corrected", cands, "ctc_dup_insert")
        return _result(c, c, "ambiguous_review" if cands else "wrong_length", cands)

    if personal and len(digits) == req_len + 1:
        cands = [v for v in variants_dup_delete(digits) if is_valid(v)]
        if len(cands) == 1:
            return _result(c, cands[0], "auto_corrected", cands, "ctc_dup_delete")

    if len(digits) != req_len:
        return _result(c, c, "wrong_length", [])
    if is_valid(c):
        return _result(c, c, "valid", [c])

    if personal:
        cands = [v for v in variants_confusion(c) if is_valid(v)]
        if len(cands) == 1:
            return _result(c, cands[0], "auto_corrected", cands, "confusion_1digit")
        if len(cands) > 1:
            return _result(c, c, "ambiguous_review", cands)
    return _result(c, c, "invalid_review", [])
