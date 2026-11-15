import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from evaluation.compare import (
    build_markdown,
    chunks_text,
    consensus,
    html_to_text,
    indra_text,
    lift_vs_gt,
    load_documents,
    numbers,
    overlap,
    pair_agreement,
    vs_consensus,
)
from persian_ocr.config import TMP_DIR


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def chunk_file(root: Path, provider: str, name: str, *contents: str) -> None:
    write_json(root / provider / "Normalized" / f"{name}.json", {"pages": [{"chunks": [{"label": "Text", "content": c} for c in contents]}]})


class HtmlToText(unittest.TestCase):
    def test_tags_are_removed_and_cells_separated(self):
        text = html_to_text("<table><tr><td>الف</td><td>ب</td></tr></table><p>ج<br/>د</p>")
        self.assertEqual(text.split(), ["الف", "ب", "ج", "د"])

    def test_entities_are_decoded(self):
        self.assertEqual(html_to_text("<p>a&nbsp;&amp;b</p>").split(), ["a", "&b"])


class Overlap(unittest.TestCase):
    def test_identical_bags(self):
        r = overlap(Counter(["الف", "ب"]), Counter(["الف", "ب"]))
        self.assertEqual((r["recall"], r["precision"], r["f1"]), (1.0, 1.0, 1.0))

    def test_recall_and_precision_differ(self):
        r = overlap(Counter(["الف", "ب", "ج", "د"]), Counter(["الف", "ب"]))
        self.assertEqual((r["recall"], r["precision"]), (0.5, 1.0))

    def test_empty_hypothesis(self):
        self.assertEqual(overlap(Counter(["الف"]), Counter())["f1"], 0.0)

    def test_numbers_keep_only_long_digit_tokens(self):
        self.assertEqual(numbers(Counter({"1234": 2, "12": 1, "الف": 3})), Counter({"1234": 2}))

    def test_pair_agreement_ignores_digit_style_and_separators(self):
        r = pair_agreement("مبلغ ۱۲۳,۴۵۶", "مبلغ 123456")
        self.assertEqual(r["words"]["f1"], 1.0)
        self.assertEqual(r["numbers"]["f1"], 1.0)


class Consensus(unittest.TestCase):
    ENTRY = {"Claude": "الف ب ج 1234", "Gemini": "الف ب د 1234", "Indra": "الف ج 1234", "Chandra": None}

    def test_consensus_is_the_shared_words(self):
        self.assertEqual(sorted(consensus(self.ENTRY)), ["1234", "الف", "ب"])

    def test_missing_reference_gives_none(self):
        self.assertIsNone(consensus({"Claude": "الف", "Gemini": None}))

    def test_recall_against_consensus(self):
        r = vs_consensus(self.ENTRY, "Indra")
        self.assertAlmostEqual(r["words"]["recall"], 2 / 3)
        self.assertEqual(r["numbers"]["recall"], 1.0)
        self.assertEqual(r["ref_words"], 3)

    def test_missing_provider_gives_none(self):
        self.assertIsNone(vs_consensus(self.ENTRY, "Chandra"))


class LiftFields(unittest.TestCase):
    def test_numbers_and_names_are_checked_against_gt(self):
        fields = {"invoice_number": "137", "total": 350000000, "seller_name": "شرکت نمونه پارس", "buyer_name": "شرکت دیگر", "invoice_date": "۱۴۰۲/۰۶/۰۱", "line_items": [{"quantity": 5, "unit_price": 70000000, "amount": 350000000}]}
        r = lift_vs_gt(fields, "شماره 137 مبلغ 350,000,000 فروشنده شرکت نمونه پارس")
        self.assertEqual((r["numbers"], r["numbers_in_gt"]), (5, 3))
        self.assertEqual(r["names"]["seller_name"], 1.0)
        self.assertAlmostEqual(r["names"]["buyer_name"], 0.5)
        self.assertIsNone(r["date"])

    def test_missing_extraction(self):
        self.assertIsNone(lift_vs_gt(None, "x"))


class Loading(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=TMP_DIR)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chunks_text_joins_chunks(self):
        chunk_file(self.root, "Claude", "a", "<p>الف</p>", "<h1>ب</h1>")
        self.assertEqual(chunks_text(self.root / "Claude" / "Normalized" / "a.json").split(), ["الف", "ب"])

    def test_missing_file_is_none(self):
        self.assertIsNone(chunks_text(self.root / "nope.json"))
        self.assertIsNone(indra_text(self.root / "nope.json"))

    def test_failed_indra_run_is_none(self):
        write_json(self.root / "Indra" / "Main" / "a.json", {"detail": "bad allocation"})
        self.assertIsNone(indra_text(self.root / "Indra" / "Main" / "a.json"))

    def test_indra_text_uses_text_dedup_of_all_pages(self):
        write_json(self.root / "Indra" / "Main" / "a.json", {"pages": [{"text_dedup": "صفحه یک"}, {"text_dedup": "صفحه دو"}]})
        self.assertEqual(indra_text(self.root / "Indra" / "Main" / "a.json"), "صفحه یک\nصفحه دو")

    def test_load_documents_and_report(self):
        for provider in ("Claude", "Gemini", "Chandra"):
            chunk_file(self.root, provider, "a", "<p>الف ب 12345</p>")
        write_json(self.root / "Indra" / "Main" / "a.json", {"pages": [{"text_dedup": "الف ب 12345"}]})
        write_json(self.root / "Lift" / "Normalized" / "a.json", {"extraction": {"total": 12345}})
        docs = load_documents(self.root)
        self.assertEqual(list(docs), ["a"])
        self.assertEqual(docs["a"]["Lift"], {"total": 12345})
        report = build_markdown(docs, self.root / "no-gt")
        self.assertIn("هم‌خوانی دوبه‌دو", report)
        self.assertIn("اجماع", report)
        self.assertNotIn("ground truth (", report)


if __name__ == "__main__":
    unittest.main()
