import unittest

from indra_ocr.pipeline import Line

from persian_ocr.config import PipelineConfig
from persian_ocr.pipeline import SUPPLEMENT_TITLE, PageOcr, _build_page, _cell_of, _covered
from persian_ocr.tables import Cell, Table

CONFIG = PipelineConfig(use_lexicon=False)


def line(text, y0, y1, conf=0.99, x0=10, x1=300):
    return Line(box=[x0, y0, x1, y1], text=text, conf=conf)


def table_with_gap():
    top = Cell(box=(0, 200, 400, 300), text="سلول بالا")
    empty = Cell(box=(0, 300, 400, 400), text="")
    bottom = Cell(box=(0, 400, 400, 500), text="سلول پایین")
    return Table(box=(0, 200, 400, 500), rows=[[top], [empty], [bottom]])


def build(lines):
    return _build_page(0, PageOcr(lines=lines, tables=[table_with_gap()]), CONFIG)


class CellLookup(unittest.TestCase):
    def test_line_in_text_cell_is_found(self):
        self.assertEqual(_cell_of(line("x", 220, 260), [table_with_gap()]).text, "سلول بالا")

    def test_line_in_gap_or_empty_cell_is_outside(self):
        self.assertIsNone(_cell_of(line("x", 340, 380), [table_with_gap()], margin=0))

    def test_title_above_table_is_outside(self):
        self.assertIsNone(_cell_of(line("عنوان", 10, 60), [table_with_gap()]))


class Coverage(unittest.TestCase):
    def test_same_words_are_covered(self):
        self.assertTrue(_covered("شرکت صنایع البرز", "نام: شرکت صنایع البرز نمونه"))

    def test_digit_style_is_ignored(self):
        self.assertTrue(_covered("۱۲۳۴۵", "کد 12345"))

    def test_number_read_with_one_extra_digit_is_covered(self):
        self.assertTrue(_covered("103,000,0001", "103,000,000"))

    def test_clearly_different_number_is_not_covered(self):
        self.assertFalse(_covered("245,200,000", "103,000,000"))

    def test_unrelated_text_is_not_covered(self):
        self.assertFalse(_covered("جمع کل فاکتور", "سلول بالا"))

    def test_short_tokens_only_count_as_covered(self):
        self.assertTrue(_covered("۱ -", "x"))


class ComposedText(unittest.TestCase):
    def test_title_between_cells_is_kept_once_with_cell_text(self):
        built = build([line("سلول بالا", 220, 260), line("صورت حساب فروش", 340, 380)])
        text = built["text_dedup"]
        self.assertIn("صورت حساب فروش", text)
        self.assertEqual(text.count("سلول بالا"), 1)

    def test_everything_is_in_reading_order(self):
        built = build([
            line("عنوان صفحه", 10, 60),
            line("سلول بالا", 220, 260),
            line("بین جدول", 340, 380),
            line("سلول پایین", 420, 460),
            line("پاورقی", 600, 640),
        ])
        text = built["text_dedup"]
        order = [text.index(s) for s in ("عنوان صفحه", "سلول بالا", "بین جدول", "سلول پایین", "پاورقی")]
        self.assertEqual(order, sorted(order))

    def test_row_markdown_is_placed_at_its_position(self):
        built = build([line("عنوان", 10, 60), line("پاورقی", 600, 640)])
        lines = built["text_dedup"].splitlines()
        self.assertEqual(lines[0], "عنوان")
        self.assertEqual(lines[-1], "پاورقی")
        self.assertEqual(lines[1:-1], ["| سلول بالا |", "| سلول پایین |"])

    def test_uncovered_confident_line_goes_to_supplement(self):
        built = build([line("جمع کل فاکتور", 220, 260, conf=0.95)])
        text = built["text_dedup"]
        self.assertIn(SUPPLEMENT_TITLE, text)
        self.assertTrue(text.endswith("جمع کل فاکتور"))

    def test_uncovered_low_confidence_line_is_not_added(self):
        built = build([line("بیللة کال", 220, 260, conf=0.4)])
        self.assertNotIn(SUPPLEMENT_TITLE, built["text_dedup"])
        self.assertEqual(len(built["low_confidence_lines"]), 1)
        self.assertIn("بیللة کال", built["raw_text"])

    def test_no_tables_keeps_all_lines(self):
        page = PageOcr(lines=[line("الف", 10, 50), line("ب", 60, 100)], tables=[])
        self.assertEqual(_build_page(0, page, CONFIG)["text_dedup"], "الف\nب")


def build_number_cell(cell_text, *lines):
    cell = Cell(box=(0, 200, 400, 300), text=cell_text)
    return _build_page(0, PageOcr(lines=list(lines), tables=[Table(box=(0, 200, 400, 300), rows=[[cell]])]), CONFIG)


def conflicts(built):
    return [r for r in built["review_queue"] if r["kind"] == "reading_conflict"]


class ReadingConflicts(unittest.TestCase):
    def test_one_digit_difference_is_reported_and_text_is_not_changed(self):
        built = build_number_cell("٢,٢٠٠,٠٠٠", line("٣,٢٠٠,٠٠٠", 220, 260))
        found = conflicts(built)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["input"], found[0]["candidates"], found[0]["status"]), ("2200000", ["3200000"], "ambiguous_review"))
        self.assertEqual(built["text_dedup"], "| ٢,٢٠٠,٠٠٠ |")

    def test_same_number_in_another_digit_style_is_not_a_conflict(self):
        self.assertEqual(conflicts(build_number_cell("٣,٢٠٠,٠٠٠", line("3200000", 220, 260))), [])

    def test_extra_digit_is_a_conflict(self):
        found = conflicts(build_number_cell("103,000,000", line("103,000,0001", 220, 260)))
        self.assertEqual((found[0]["input"], found[0]["candidates"]), ("103000000", ["1030000001"]))

    def test_clearly_different_number_is_not_a_conflict_but_goes_to_supplement(self):
        built = build_number_cell("103,000,000", line("245,200,000", 220, 260))
        self.assertEqual(conflicts(built), [])
        self.assertIn(SUPPLEMENT_TITLE, built["text_dedup"])

    def test_short_numbers_are_ignored(self):
        self.assertEqual(conflicts(build_number_cell("12", line("13", 220, 260))), [])

    def test_words_that_differ_are_not_conflicts(self):
        self.assertEqual(conflicts(build_number_cell("شرکت الف", line("شرکت ب", 220, 260))), [])

    def test_nearest_number_in_a_multi_number_cell_is_chosen(self):
        found = conflicts(build_number_cell("1234567 و 9999999", line("1234577", 220, 260)))
        self.assertEqual((found[0]["input"], found[0]["candidates"]), ("1234567", ["1234577"]))

    def test_repeated_conflict_is_reported_once(self):
        built = build_number_cell("2200000", line("3200000", 220, 240), line("3200000", 245, 265))
        self.assertEqual(len(conflicts(built)), 1)

    def test_low_confidence_line_is_reported_too(self):
        self.assertEqual(len(conflicts(build_number_cell("2200000", line("3200000", 220, 260, conf=0.4)))), 1)

    def test_confidences_of_both_readings_are_recorded(self):
        found = conflicts(build_number_cell("2200000", line("3200000", 220, 260, conf=0.9)))
        self.assertEqual((found[0]["line_conf"], found[0]["cell_conf"]), (0.9, 0.0))

    def test_page_without_tables_has_no_conflict(self):
        page = PageOcr(lines=[line("3200000", 10, 50)], tables=[])
        self.assertEqual(conflicts(_build_page(0, page, CONFIG)), [])

    def test_existing_review_items_are_kept(self):
        built = build_number_cell("2200000", line("3200000", 220, 260), line("شناسه ملی: 10865482173", 600, 640))
        kinds = {r["kind"] for r in built["review_queue"]}
        self.assertEqual(kinds, {"reading_conflict", "legal"})


if __name__ == "__main__":
    unittest.main()
