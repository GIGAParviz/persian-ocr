from __future__ import annotations

from dataclasses import dataclass, field

BBox = tuple[int, int, int, int]


@dataclass
class Cell:
    box: BBox
    text: str = ""
    conf: float = 0.0


@dataclass
class Table:
    box: BBox
    rows: list[list[Cell]] = field(default_factory=list)
