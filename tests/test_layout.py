import unittest
from types import SimpleNamespace

from persian_ocr.api.layout import build_layout


def line(box, text, conf=0.9):
    return SimpleNamespace(box=box, text=text, conf=conf)


def cell(box, text, conf=0.8):
    return SimpleNamespace(box=box, text=text, conf=conf)


class LayoutTests(unittest.TestCase):
    def test_lines_keep_image_coordinates_and_corrected_text(self):
        page = SimpleNamespace(lines=[line([80, 10, 180, 30], "خام"), line([10, 55, 100, 75], "دوم")], tables=[])
        layout = build_layout((200, 100), page, "اصلاح شده\nدوم")
        self.assertEqual(layout["size"], [200, 100])
        self.assertEqual([item["box"] for item in layout["items"]], [[80, 10, 180, 30], [10, 55, 100, 75]])
        self.assertEqual([item["text"] for item in layout["items"]], ["اصلاح شده", "دوم"])

    def test_table_cells_are_positioned_and_duplicate_lines_are_omitted(self):
        table = SimpleNamespace(box=[10, 20, 190, 90], rows=[[cell([10, 20, 100, 50], "نام"), cell([100, 20, 190, 50], "مبلغ")]])
        page = SimpleNamespace(lines=[line([30, 25, 80, 45], "نام"), line([20, 5, 170, 18], "عنوان")], tables=[table])
        layout = build_layout((200, 100), page, "نام\nعنوان")
        self.assertEqual(layout["tables"], [[10, 20, 190, 90]])
        self.assertEqual(layout["cells"], [[10, 20, 100, 50], [100, 20, 190, 50]])
        self.assertEqual(sorted(item["text"] for item in layout["items"]), ["عنوان", "مبلغ", "نام"])

    def test_boxes_are_clamped_to_page(self):
        page = SimpleNamespace(lines=[line([-20, -10, 150, 30], "متن"), line([110, 10, 140, 40], "خارج")], tables=[])
        layout = build_layout((100, 80), page, "متن\nخارج")
        self.assertEqual([item["box"] for item in layout["items"]], [[0, 0, 100, 30]])


if __name__ == "__main__":
    unittest.main()
