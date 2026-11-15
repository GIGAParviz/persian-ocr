import base64
import json
import unittest
from collections import Counter

import cv2
import numpy as np
from indra_ocr.pipeline import Line

from evaluation.errors import (
    TEMPLATE,
    Item,
    build_rows,
    classify,
    collect_items,
    diff_html,
    gt_context,
    is_annotation,
    label_line,
    make_crop,
    missed_numbers,
    nearest_item,
    number_tokens,
    summarize,
)
from persian_ocr.pipeline import PageOcr
from persian_ocr.tables import Cell, Table


def line(text, box=(100, 100, 400, 140), conf=0.9):
    return Line(box=list(box), text=text, conf=conf)


def jpeg(width=800, height=600):
    img = np.full((height, width), 255, np.uint8)
    cv2.putText(img, "1234", (120, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


class Missed(unittest.TestCase):
    def test_numbers_need_four_digits(self):
        self.assertEqual(number_tokens("کد 12 و 12345 و ۶۷۸۹۰"), ["12345", "67890"])

    def test_only_unmatched_gt_numbers_are_returned_in_order(self):
        self.assertEqual(missed_numbers("الف 1111 ب 2222 ج 3333", "2222 و 3333"), ["1111"])

    def test_repeated_numbers_are_counted(self):
        self.assertEqual(missed_numbers("1111 و 1111", "1111"), ["1111"])

    def test_separators_and_digit_style_are_ignored(self):
        self.assertEqual(missed_numbers("مبلغ 62,376,000", "مبلغ ۶۲۳۷۶۰۰۰"), [])


class Kinds(unittest.TestCase):
    def test_not_read(self):
        self.assertEqual(classify("12345", ""), "missing")

    def test_dropped_and_added(self):
        self.assertEqual(classify("12345", "1245"), "dropped")
        self.assertEqual(classify("12345", "123945"), "added")

    def test_zero_runs(self):
        self.assertEqual(classify("785000", "78500"), "dropped_zero")
        self.assertEqual(classify("62376000", "623760000"), "added_zero")

    def test_single_zero_is_not_a_run(self):
        self.assertEqual(classify("1203", "123"), "dropped")

    def test_replaced_and_multi(self):
        self.assertEqual(classify("12345", "12845"), "replaced")
        self.assertEqual(classify("12345", "98765"), "multi")


class Diff(unittest.TestCase):
    def test_changed_digits_are_marked_on_both_sides(self):
        left, right = diff_html("12345", "12845")
        self.assertEqual(left, "12<mark>3</mark>45")
        self.assertEqual(right, "12<mark>8</mark>45")

    def test_dropped_digit_is_marked_only_in_ground_truth(self):
        left, right = diff_html("12345", "1245")
        self.assertIn("<mark>3</mark>", left)
        self.assertNotIn("<mark>", right)


class Locating(unittest.TestCase):
    def pages(self):
        cell = Cell(box=(0, 200, 300, 260), text="1234999", conf=0.9)
        return [PageOcr(lines=[line("شماره 1234567", (50, 50, 500, 90)), line("کد پستی : ۱۹۶")], tables=[Table(box=(0, 200, 300, 260), rows=[[cell]])])]

    def test_items_come_from_lines_and_cells(self):
        items = collect_items(self.pages())
        self.assertEqual(sorted(i.token for i in items), ["1234567", "1234999"])

    def test_nearest_reading_is_found_and_consumed(self):
        items = collect_items(self.pages())
        pool = Counter({"1234567": 1, "1234999": 1})
        found = nearest_item("1234577", items, pool)
        self.assertEqual(found.token, "1234567")
        self.assertEqual(pool["1234567"], 0)
        self.assertIsNone(nearest_item("1234577", [Item(0, "1234567", (0, 0, 1, 1))], pool))

    def test_far_readings_are_ignored(self):
        items = [Item(0, "9999999", (0, 0, 1, 1))]
        self.assertIsNone(nearest_item("1234567", items, Counter({"9999999": 1})))

    def test_label_line_is_found_by_text(self):
        found = label_line("کد پستی: 1946827351", "1946827351", self.pages())
        self.assertEqual(found, (0, (100.0, 100.0, 400.0, 140.0)))

    def test_short_line_inside_the_label_is_not_a_match(self):
        pages = [PageOcr(lines=[line("۱", (10, 10, 30, 50)), line("پ", (10, 60, 30, 100))], tables=[])]
        self.assertIsNone(label_line("کد پستی ۱۰ رقمی: 1946827351", "1946827351", pages))

    def test_key_before_the_colon_is_the_label(self):
        pages = [PageOcr(lines=[line("ارزش افزوده (۱۰٪)", (60, 300, 300, 340))], tables=[])]
        found = label_line("ارزش افزوده (۱۰٪): ۶,۲۳۷,۶۰۰ ریال", "6237600", pages)
        self.assertEqual(found, (0, (60.0, 300.0, 300.0, 340.0)))

    def test_annotation_lines_are_never_located(self):
        pages = [PageOcr(lines=[line("تطبیق دیکشنری سازمان", (60, 300, 400, 340))], tables=[])]
        self.assertIsNone(label_line("[تطبیق دیکشنری سازمان: phone=21234567]", "21234567", pages))
        self.assertTrue(is_annotation("[تطبیق دیکشنری سازمان: phone=21234567]"))
        self.assertFalse(is_annotation("کد پستی: 1946827351"))

    def test_no_label_means_no_location(self):
        self.assertIsNone(label_line("1946827351", "1946827351", self.pages()))

    def test_context_is_the_gt_line(self):
        self.assertEqual(gt_context("الف\n  کد پستی: 1946827351 \nب", "1946827351"), "کد پستی: 1946827351")


class Crops(unittest.TestCase):
    def test_crop_is_a_jpeg_with_a_readable_height(self):
        data = base64.b64decode(make_crop(jpeg(), (110, 100, 300, 140)))
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        self.assertGreaterEqual(img.shape[0], 100)
        self.assertTrue((img[:, :, 2] > 150).any() and (img[:, :, 0] < 100).any())

    def test_box_at_the_page_edge_does_not_crash(self):
        self.assertTrue(make_crop(jpeg(), (0, 0, 50, 20)))
        self.assertTrue(make_crop(jpeg(), (780, 580, 800, 600), wide=True))

    def test_label_crop_reaches_the_value_below_the_label(self):
        img = np.full((600, 800), 255, np.uint8)
        img[230:260, 320:380] = 0
        ok, buf = cv2.imencode(".png", img)
        page = buf.tobytes()

        def black_pixels(wide):
            crop = cv2.imdecode(np.frombuffer(base64.b64decode(make_crop(page, (300, 100, 400, 140), wide=wide)), np.uint8), cv2.IMREAD_GRAYSCALE)
            return int((crop < 40).sum())

        self.assertEqual(black_pixels(False), 0)
        self.assertGreater(black_pixels(True), 500)

    def test_label_crop_reaches_the_value_beside_the_label(self):
        img = np.full((600, 800), 255, np.uint8)
        img[100:140, 440:480] = 0
        ok, buf = cv2.imencode(".png", img)
        page = buf.tobytes()

        def black_pixels(wide):
            crop = cv2.imdecode(np.frombuffer(base64.b64decode(make_crop(page, (300, 100, 400, 140), wide=wide)), np.uint8), cv2.IMREAD_GRAYSCALE)
            return int((crop < 40).sum())

        self.assertEqual(black_pixels(False), 0)
        self.assertGreater(black_pixels(True), 500)


class Rows(unittest.TestCase):
    def test_rows_and_summary(self):
        pages = [PageOcr(lines=[line("شماره 1234577", (110, 100, 400, 140)), line("کد پستی : ۱۹۶۵")], tables=[])]
        gt = "شماره 1234567\nکد پستی: 1946827351\nمبلغ 5555555"
        hyp = "شماره 1234577\nکد پستی ۱۹۶۵"
        rows = build_rows("doc1", gt, hyp, pages, [jpeg()])
        by_gt = {r["gt"]: r for r in rows}
        self.assertEqual(set(by_gt), {"1234567", "1946827351", "5555555"})
        self.assertEqual((by_gt["1234567"]["kind"], by_gt["1234567"]["where"], by_gt["1234567"]["ocr"]), ("replaced", "reading", "1234577"))
        self.assertTrue(by_gt["1234567"]["crop"])
        self.assertEqual((by_gt["1946827351"]["where"], by_gt["1946827351"]["kind"]), ("label", "missing"))
        self.assertTrue(by_gt["1946827351"]["crop"])
        self.assertEqual((by_gt["5555555"]["where"], by_gt["5555555"]["crop"]), ("unknown", ""))
        self.assertEqual(len({r["id"] for r in rows}), 3)
        s = summarize(rows)
        self.assertEqual((s["total"], s["located"], s["by_doc"]), (3, 2, {"doc1": 3}))


class Annotations(unittest.TestCase):
    def test_annotation_row_has_no_crop_and_says_so(self):
        pages = [PageOcr(lines=[line("متن دیگر", (110, 100, 400, 140))], tables=[])]
        rows = build_rows("doc1", "[تطبیق دیکشنری سازمان: phone=21234567]", "متن دیگر", pages, [jpeg()])
        self.assertEqual((rows[0]["where"], rows[0]["crop"], rows[0]["kind"]), ("annotation", "", "missing"))


class Template(unittest.TestCase):
    def test_template_has_one_placeholder_and_verdict_buttons(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(text.count("__DATA__"), 1)
        self.assertIn("data-v", text)

    def test_rows_survive_the_json_roundtrip(self):
        from evaluation.dashboard import render_page

        out = render_page({"rows": [{"context": "</script>"}]}, "<script id='data'>__DATA__</script>")
        self.assertEqual(json.loads(out.split(">", 1)[1].rsplit("</script>", 1)[0]), {"rows": [{"context": "</script>"}]})


if __name__ == "__main__":
    unittest.main()
