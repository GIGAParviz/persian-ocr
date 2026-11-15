import unittest

import cv2
import numpy as np

from persian_ocr.tables import find_cells, group_rows, table_to_markdown
from persian_ocr.tables.models import Cell, Table
from persian_ocr.tiling import line_iou, merge_lines, tile_bounds
from indra_ocr.pipeline import Line


def grid_image(rows: int, cols: int, cell_w: int = 220, cell_h: int = 80) -> np.ndarray:
    img = np.full((rows * cell_h + 200, cols * cell_w + 200), 255, np.uint8)
    x0, y0 = 100, 100
    for r in range(rows + 1):
        cv2.line(img, (x0, y0 + r * cell_h), (x0 + cols * cell_w, y0 + r * cell_h), 0, 3)
    for c in range(cols + 1):
        cv2.line(img, (x0 + c * cell_w, y0), (x0 + c * cell_w, y0 + rows * cell_h), 0, 3)
    return img


class Cells(unittest.TestCase):
    def test_grid_cells_found(self):
        cells = find_cells(grid_image(4, 5))
        self.assertEqual(len(cells), 20)

    def test_rows_grouped_and_ordered_right_to_left(self):
        rows = group_rows(find_cells(grid_image(3, 4)))
        self.assertEqual([len(r) for r in rows], [4, 4, 4])
        for row in rows:
            xs = [c[2] for c in row]
            self.assertEqual(xs, sorted(xs, reverse=True))

    def test_blank_page_has_no_cells(self):
        self.assertEqual(find_cells(np.full((500, 500), 255, np.uint8)), [])


class Markdown(unittest.TestCase):
    def test_empty_cells_skipped_and_pipes_escaped(self):
        table = Table(box=(0, 0, 10, 10), rows=[[Cell((0, 0, 1, 1), "الف|ب"), Cell((1, 0, 2, 1), ""), Cell((2, 0, 3, 1), "ج")], [Cell((0, 1, 1, 2), "")]])
        self.assertEqual(table_to_markdown(table), "| الف/ب | ج |")


class Tiling(unittest.TestCase):
    def test_tiles_overlap(self):
        top_end, bottom_start = tile_bounds(1000, 0.18)
        self.assertEqual((top_end, bottom_start), (590, 410))

    def test_iou(self):
        self.assertEqual(line_iou([0, 0, 10, 10], [20, 20, 30, 30]), 0.0)
        self.assertEqual(line_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)

    def test_overlap_keeps_higher_confidence_line(self):
        a = Line(box=[0, 100, 200, 130], text="کم", conf=0.5)
        b = Line(box=[0, 0, 200, 30], text="زیاد", conf=0.9)
        merged = merge_lines([a], [b], y_offset=100)
        self.assertEqual([m.text for m in merged], ["زیاد"])

    def test_distinct_lines_both_kept(self):
        a = Line(box=[0, 0, 200, 30], text="الف", conf=0.9)
        b = Line(box=[0, 0, 200, 30], text="ب", conf=0.9)
        self.assertEqual(len(merge_lines([a], [b], y_offset=500)), 2)


if __name__ == "__main__":
    unittest.main()
