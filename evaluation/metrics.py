from __future__ import annotations

import re
from collections import Counter

from rapidfuzz.distance import Levenshtein

from persian_ocr.text.normalize import normalize, normalize_digits
from persian_ocr.text.validators import is_valid_legal_id, is_valid_nid

_TOKEN = re.compile(r"[\u0600-\u06FF]+|[A-Za-z]+|\d+")
_PUNCTUATION = re.compile(r"[\u060C\u061B\u061F\u066A-\u066D\u06D4]")
_ID_CONTEXT = re.compile(r"(?:شناسه|کد|شماره)\s*(?:مل[یی]|اقتصادی)")
_ID_NUMBER = re.compile(r"(?<![\d,،٬])\d{10,11}(?![\d,،٬])")


def prep(text: str) -> str:
    t = normalize_digits(normalize(text))
    t = re.sub(r"(?<=\d)[,،٬](?=\d)", "", t)
    return _PUNCTUATION.sub(" ", t)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(prep(text))


def has_invalid_id(line: str) -> bool:
    text = normalize_digits(normalize(line))
    return bool(_ID_CONTEXT.search(text)) and any(not (is_valid_legal_id(v) if len(v) == 11 else is_valid_nid(v)) for v in _ID_NUMBER.findall(text))


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def document_metrics(gt: str, hyp: str) -> dict:
    gt_tok, hyp_tok = tokens(gt), tokens(hyp)
    N, H = len(gt_tok), len(hyp_tok)
    gt_bag, hyp_bag = Counter(gt_tok), Counter(hyp_tok)
    M = sum((gt_bag & hyp_bag).values())

    gt_chars = re.sub(r"\s+", " ", prep(gt)).strip()
    hyp_chars = re.sub(r"\s+", " ", prep(hyp)).strip()

    lines = [l for l in gt.splitlines() if tokens(l)]
    remaining = Counter(hyp_bag)
    bad = adj_bad = adj_n = 0
    for line in lines:
        need = Counter(tokens(line))
        missing = not all(remaining[k] >= v for k, v in need.items())
        if not missing:
            remaining -= need
        bad += missing
        if not has_invalid_id(line):
            adj_n += 1
            adj_bad += missing

    gt_nums = Counter(t for t in gt_tok if t.isdigit() and len(t) >= 4)
    hyp_nums = Counter(t for t in hyp_tok if t.isdigit() and len(t) >= 4)
    return {
        "N": N, "H": H, "M": M, "gt_chars": len(gt_chars),
        "word_acc": M / max(N, 1),
        "word_prec": M / max(H, 1),
        "wer_ordered": Levenshtein.distance(gt_tok, hyp_tok) / max(N, 1),
        "wer_free_errors": (N - M) + max(0, H - N),
        "wer_free": ((N - M) + max(0, H - N)) / max(N, 1),
        "cer": Levenshtein.distance(gt_chars, hyp_chars) / max(len(gt_chars), 1),
        "lines": len(lines), "ser": bad / max(len(lines), 1), "ser_bad": bad,
        "ser_adj": adj_bad / max(adj_n, 1), "ser_adj_bad": adj_bad, "ser_adj_n": adj_n,
        "num_n": sum(gt_nums.values()),
        "num_m": sum((gt_nums & hyp_nums).values()),
        "num_acc": sum((gt_nums & hyp_nums).values()) / max(sum(gt_nums.values()), 1),
    }


def aggregate(docs: list[dict]) -> dict:
    N = sum(d["N"] for d in docs)
    H = sum(d["H"] for d in docs)
    M = sum(d["M"] for d in docs)
    chars = sum(d["gt_chars"] for d in docs)
    lines = sum(d["lines"] for d in docs)
    n, h, c, l = max(N, 1), max(H, 1), max(chars, 1), max(lines, 1)
    return {
        "N": N, "lines": lines,
        "word_acc": M / n, "word_prec": M / h, "f1": f1(M / h, M / n),
        "wer_ordered": sum(d["wer_ordered"] * d["N"] for d in docs) / n,
        "wer_free": sum(d["wer_free_errors"] for d in docs) / n,
        "cer": sum(d["cer"] * d["gt_chars"] for d in docs) / c,
        "ser": sum(d["ser_bad"] for d in docs) / l,
        "ser_adj": sum(d["ser_adj_bad"] for d in docs) / max(sum(d["ser_adj_n"] for d in docs), 1),
        "num_acc": sum(d["num_m"] for d in docs) / max(sum(d["num_n"] for d in docs), 1),
    }
