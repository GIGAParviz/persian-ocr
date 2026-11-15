from __future__ import annotations

import re

from .accounting import reconcile_capital_shares
from .correction import correct_by_checksum
from .dates import normalize_jalali_dates
from .lexicon import apply_domain_lexicon
from .normalize import normalize, normalize_digits

_CONTEXT_NID = re.compile(r"((?:شماره|کد)\s*مل[یی]\s*[:=]?\s*)(?<!\d)(\d{9,11})(?!\d)")
_CONTEXT_LEGAL = re.compile(r"(شناسه\s*مل[یی]\s*[:=]?\s*)(?<!\d)(\d{10,12})(?!\d)")
_REVIEW_STATUSES = ("ambiguous_review", "invalid_review", "wrong_length")


def _fix_ids(text: str, pattern: re.Pattern, kind: str, corrections: list[dict], review: list[dict]) -> str:
    def fix(m: re.Match) -> str:
        prefix, token = m.group(1), m.group(2)
        res = correct_by_checksum(token, kind=kind)
        if res["status"] == "auto_corrected":
            corrections.append(res)
            return prefix + res["output"]
        if res["status"] in _REVIEW_STATUSES:
            review.append({"kind": kind, "context": m.group(0), **res})
        return m.group(0)

    return pattern.sub(fix, text)


def postprocess_text(raw_text: str, use_lexicon: bool = True) -> dict:
    text = normalize_digits(normalize(raw_text))
    corrections: list[dict] = []
    review_queue: list[dict] = []

    text = _fix_ids(text, _CONTEXT_NID, "nid", corrections, review_queue)
    text = _fix_ids(text, _CONTEXT_LEGAL, "legal", corrections, review_queue)
    text = normalize_jalali_dates(text, corrections, review_queue)
    text = reconcile_capital_shares(text, corrections)
    if use_lexicon:
        text = apply_domain_lexicon(text, corrections)

    return {"text": text, "corrections": corrections, "review_queue": review_queue}
