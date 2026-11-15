from __future__ import annotations

import re


def _valid(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def normalize_jalali_dates(text: str, corrections: list[dict], review: list[dict]) -> str:
    def normalize_separators(m: re.Match) -> str:
        month, day = int(m.group(2)), int(m.group(3))
        if not _valid(month, day):
            return m.group(0)
        return f"{m.group(1)}/{month:02d}/{day:02d}"

    text = re.sub(
        r"(?<!\d)(1[34]\d{2})\s*[/.٫-]\s*(\d{1,2})\s*[/.٫-]\s*(\d{1,2})(?!\d)",
        normalize_separators,
        text,
    )

    def fix_missing_slash(m: re.Match) -> str:
        year, md = m.group(1), m.group(2)
        month, day = int(md[:2]), int(md[2:])
        if _valid(month, day):
            fixed = f"{year}/{month:02d}/{day:02d}"
            corrections.append({"kind": "jalali_date", "input": m.group(0), "output": fixed, "status": "auto_corrected"})
            return fixed
        return m.group(0)

    text = re.sub(r"(?<!\d)(1[34]\d{2})[/.](\d{4})(?!\d)", fix_missing_slash, text)

    for m in re.finditer(r"(مورخ\s*)([.٫]?)(\b1[34]\d{2})[/.](0[1-9]|1[0-2])([123])([.٫]?)(?!\d)", text):
        _, dot1, year, month, day_first, dot2 = m.groups()
        if dot1 or dot2:
            days = [f"0{day_first}"] + [f"{day_first}{d}" for d in range(10) if _valid(int(month), int(f"{day_first}{d}"))]
            review.append({
                "kind": "jalali_date",
                "input": m.group(0).strip(),
                "status": "ambiguous_review",
                "candidates": [f"{year}/{month}/{d}" for d in days],
            })

    def fix_extra_year_digit(m: re.Match) -> str:
        fixed = normalize_separators(m)
        if fixed != m.group(0):
            corrections.append({"kind": "jalali_date", "input": m.group(0), "output": fixed, "status": "auto_corrected"})
        return fixed

    return re.sub(r"\b(1[34]\d{2})0\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\b", fix_extra_year_digit, text)
