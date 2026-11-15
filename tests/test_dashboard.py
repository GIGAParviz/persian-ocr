import base64
import json
import unittest
from pathlib import Path

from evaluation.dashboard import Marker, build_doc, mark_tokens, render_html, render_page, source_files
from persian_ocr.config import EVAL_DATA_DIR
from persian_ocr.pdfio import preview_jpeg, preview_jpeg_b64
from persian_ocr.pipeline import SUPPLEMENT_TITLE

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "invoice-sample.png"


def page(text, **kw):
    base = {"page": 1, "text_dedup": text, "tables_markdown": [], "corrections": [], "review_queue": [], "low_confidence_lines": [], "invoice": None}
    base.update(kw)
    return base


def low(text):
    return {"text": text, "conf": 0.5, "box": [0, 0, 1, 1]}


class Marking(unittest.TestCase):
    def test_mark_tokens_skips_short_and_long_values(self):
        self.assertEqual(mark_tokens(["3499838389", "12", None, "x" * 100]), {"3499838389"})

    def test_digit_style_does_not_matter(self):
        self.assertIn("class='w fix'", Marker(fix={"3499838389"}).word("۳۴۹۹۸۳۸۳۸۹"))

    def test_unmarked_word_is_escaped_text(self):
        self.assertEqual(Marker().word("<b>"), "&lt;b&gt;")

    def test_fix_wins_over_review(self):
        self.assertIn("w fix", Marker(fix={"1234567892"}, review={"1234567892"}).word("1234567892"))


class Rendering(unittest.TestCase):
    def render(self, text, low=frozenset(), **kw):
        return render_html(text, Marker(**kw), low)

    def test_plain_lines(self):
        self.assertEqual(self.render("الف ب\nج").count("<div class='l'>"), 2)

    def test_table_rows_become_table_cells(self):
        out = self.render("عنوان\n| الف | ب |\n| ج | د |\nپایان")
        self.assertEqual(out.count("<table class='t'>"), 1)
        self.assertEqual(out.count("<td>"), 4)
        self.assertEqual(out.count("<tr>"), 2)

    def test_cell_words_are_marked(self):
        self.assertIn("<td><span class='w fix'>3499838389</span></td>", self.render("| 3499838389 | ب |", fix={"3499838389"}))

    def test_corrected_and_review_values_are_marked(self):
        out = self.render("کد 3499838389 و 1234567892", fix={"3499838389"}, review={"1234567892"})
        self.assertIn("<span class='w fix'>3499838389</span>", out)
        self.assertIn("<span class='w rev'>1234567892</span>", out)

    def test_low_confidence_line_gets_class(self):
        out = self.render("خط مشکوک\nخط خوب", low=frozenset({"خط مشکوک"}))
        self.assertIn("<div class='l low'>خط مشکوک</div>", out)
        self.assertIn("<div class='l'>خط خوب</div>", out)

    def test_supplement_title_is_styled(self):
        self.assertIn("<div class='sup'>", self.render(SUPPLEMENT_TITLE + "\nالف"))

    def test_html_is_escaped(self):
        self.assertNotIn("<script>", self.render("<script>alert(1)</script>"))


class Preview(unittest.TestCase):
    @unittest.skipUnless(SAMPLE.exists(), "sample image missing")
    def test_size_matches_the_decoded_image(self):
        import cv2
        import numpy as np

        data, width, height = preview_jpeg(SAMPLE, 0)
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual((decoded.shape[1], decoded.shape[0]), (width, height))
        self.assertEqual(preview_jpeg_b64(SAMPLE, 0), base64.b64encode(data).decode("ascii"))


@unittest.skipUnless(SAMPLE.exists(), "sample image missing")
class Document(unittest.TestCase):
    RESULT = {"file": "invoice-sample.png", "time_sec": 1.5, "pages": [page("الف ب ج", low_confidence_lines=[low("ج")])]}

    def test_page_data(self):
        doc = build_doc(SAMPLE, self.RESULT)
        p = doc["pages"][0]
        self.assertEqual((doc["name"], doc["file"], doc["time"]), ("invoice-sample", "invoice-sample.png", 1.5))
        self.assertTrue(p["image"])
        self.assertGreater(p["size"][0], 0)
        self.assertGreater(p["size"][1], 0)
        self.assertEqual(p["stats"], {"words": 3, "tables": 0, "corr": 0, "rev": 0, "low": 1})
        self.assertNotIn("m", doc)

    def test_no_ground_truth_data_is_included(self):
        doc = build_doc(SAMPLE, self.RESULT)
        self.assertEqual(set(doc), {"name", "file", "time", "mismatch", "focus", "pages"})
        self.assertNotIn("class='w x'", doc["pages"][0]["html"])

    def test_focus_page_is_the_one_with_most_issues(self):
        result = {"file": "x", "time_sec": 1, "pages": [page("الف"), page("ب", page=2, low_confidence_lines=[low("ب")] * 3)]}
        self.assertEqual(build_doc(SAMPLE, result)["focus"], 1)

    def test_invoice_mismatches_are_summed(self):
        invoice = {"header": {}, "parties": {}, "items": [], "totals": {}, "checks": [], "check_summary": {"ok": 3, "mismatch": 2}}
        result = {"file": "x", "time_sec": 1, "pages": [page("الف", invoice=invoice), page("ب", page=2, invoice=invoice)]}
        self.assertEqual(build_doc(SAMPLE, result)["mismatch"], 4)


class Template(unittest.TestCase):
    def test_data_is_embedded_and_script_end_is_escaped(self):
        out = render_page({"x": "</script><b>"}, "<script id='data'>__DATA__</script>")
        self.assertNotIn("</script><b>", out)
        payload = out.split(">", 1)[1].rsplit("</script>", 1)[0]
        self.assertEqual(json.loads(payload), {"x": "</script><b>"})

    def test_real_template_has_one_placeholder_and_no_ground_truth_ui(self):
        from evaluation.dashboard import TEMPLATE

        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(text.count("__DATA__"), 1)
        self.assertNotIn("gtcol", text)
        self.assertIn("rotL", text)


@unittest.skipUnless(EVAL_DATA_DIR.exists(), "eval_data missing")
class Sources(unittest.TestCase):
    def test_eval_folder_lists_only_documents(self):
        names = {p.name for p in source_files(EVAL_DATA_DIR)}
        self.assertTrue(all(n.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")) for n in names))
        self.assertNotIn("eval-data-compare", names)


if __name__ == "__main__":
    unittest.main()
