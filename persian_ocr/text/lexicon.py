from __future__ import annotations

import json
import re
from functools import lru_cache

from ..config import LEXICON_PATH


@lru_cache(maxsize=1)
def _load() -> dict:
    if not LEXICON_PATH.exists():
        return {}
    try:
        return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_domain_lexicon(text: str, corrections: list[dict]) -> str:
    for entity in _load().get("entities", []):
        if not any(t in text for t in entity.get("triggers", [])):
            continue
        recovered = []
        for name, spec in entity.get("fields", {}).items():
            value = str(spec["value"])
            if value in text:
                continue
            for pattern in spec.get("context_patterns", []):
                m = re.search(pattern, text)
                if m:
                    corrections.append({"kind": f"domain_lexicon:{name}", "input": m.group(0), "output": value, "status": "auto_corrected"})
                    recovered.append(f"{name}={value}")
                    break
        if recovered:
            text += "\n[تطبیق دیکشنری سازمان: " + " | ".join(recovered) + "]"
    return text
