from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .metrics import prep

VERDICTS_PATH = Path(__file__).with_name("number_verdicts.json")
MASKED_VERDICTS = ("gt", "image")


def load_verdicts(path: Path = VERDICTS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def masks_for(doc: str, verdicts: list[dict] | None = None) -> Counter:
    verdicts = load_verdicts() if verdicts is None else verdicts
    return Counter(v["gt"] for v in verdicts if v["doc"] == doc and v["verdict"] in MASKED_VERDICTS)


def mask_numbers(text: str, numbers: Counter) -> str:
    left = Counter(numbers)
    out = []
    for line in text.splitlines():
        if any(left.values()):
            norm, changed = prep(line), False
            for number in [n for n, c in left.items() if c > 0]:
                norm, hits = re.subn(rf"(?<!\d){re.escape(number)}(?!\d)", " ", norm, count=left[number])
                if hits:
                    left[number] -= hits
                    changed = True
            if changed:
                line = norm
        out.append(line)
    return "\n".join(out)


def load_gt(path: Path, masked: bool = True, verdicts: list[dict] | None = None) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return mask_numbers(text, masks_for(Path(path).stem, verdicts)) if masked else text
