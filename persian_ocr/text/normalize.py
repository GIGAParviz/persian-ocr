from __future__ import annotations

import re
import unicodedata

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_TO_PERSIAN = str.maketrans("٠١٢٣٤٥٦٧٨٩يكۀٱ", "0123456789یکهآ")

_INVISIBLE = re.compile(r"[\u200b\u200c\u2066-\u2069\u202a-\u202e\ufeff]")
_DECORATIVE = re.compile(r"[📍📞📠🌐✉️\U0001f4cd-\U0001f9ef]|[\U0001f300-\U0001faff]")
_SPACES = re.compile(r"[\u00a0\u2007\u202f\u3000\t\r\f\v]")


def normalize_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_TO_PERSIAN)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ARABIC_TO_PERSIAN)
    text = _INVISIBLE.sub("", text)
    text = _DECORATIVE.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return re.sub(r"[ ]{2,}", " ", text).strip()
