import tempfile
import unittest
from collections import Counter
from pathlib import Path

from evaluation.groundtruth import MASKED_VERDICTS, VERDICTS_PATH, load_gt, load_verdicts, mask_numbers, masks_for
from evaluation.metrics import tokens
from persian_ocr.config import EVAL_DATA_DIR, TMP_DIR

KINDS = {"missing", "dropped", "dropped_zero", "added", "added_zero", "replaced", "multi"}


def verdict(doc, gt, kind="multi", value="gt"):
    return {"doc": doc, "gt": gt, "ocr": "", "kind": kind, "verdict": value}


class Masking(unittest.TestCase):
    def test_number_is_removed_and_the_rest_of_the_line_stays(self):
        out = mask_numbers("کد پستی: 1946827351 تهران", Counter({"1946827351": 1}))
        self.assertNotIn("1946827351", out)
        self.assertEqual(out.split(), ["کد", "پستی:", "تهران"])

    def test_persian_digits_and_separators_are_matched(self):
        out = mask_numbers("مبلغ: ۶۲,۳۷۶,۰۰۰ ریال", Counter({"62376000": 1}))
        self.assertEqual(out.split(), ["مبلغ:", "ریال"])

    def test_only_the_judged_number_of_occurrences_is_removed(self):
        out = mask_numbers("الف 1111\nب 1111\nج 1111", Counter({"1111": 2}))
        self.assertEqual(sum("1111" in line for line in out.splitlines()), 1)

    def test_longer_and_shorter_numbers_are_not_touched(self):
        out = mask_numbers("a 1000 b 10000 c 100", Counter({"1000": 1}))
        self.assertEqual(out.split(), ["a", "b", "10000", "c", "100"])

    def test_other_lines_are_returned_unchanged(self):
        text = "سطر ۱۲۳۴۵\nسطر دیگر 1111"
        self.assertEqual(mask_numbers(text, Counter({"1111": 1})).splitlines()[0], "سطر ۱۲۳۴۵")

    def test_nothing_to_mask_keeps_the_text(self):
        self.assertEqual(mask_numbers("الف ۱۲۳۴۵\nب", Counter()), "الف ۱۲۳۴۵\nب")

    def test_number_inside_a_code_with_letters_is_found(self):
        out = mask_numbers("A1171W02DAB0000000300D7", Counter({"0000000300": 1}))
        self.assertNotIn("0000000300", out)


class Verdicts(unittest.TestCase):
    VERDICTS = [verdict("d1", "1111", value="gt"), verdict("d1", "2222", value="ocr"), verdict("d1", "3333", value="image"), verdict("d2", "1111", value="gt"), verdict("d1", "1111", value="gt")]

    def test_only_gt_and_image_verdicts_mask(self):
        self.assertEqual(MASKED_VERDICTS, ("gt", "image"))
        self.assertEqual(masks_for("d1", self.VERDICTS), Counter({"1111": 2, "3333": 1}))

    def test_other_documents_are_independent(self):
        self.assertEqual(masks_for("d2", self.VERDICTS), Counter({"1111": 1}))
        self.assertEqual(masks_for("d3", self.VERDICTS), Counter())

    def test_ocr_verdict_keeps_the_number_in_the_ground_truth(self):
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
            path = Path(tmp) / "d1.txt"
            path.write_text("الف 1111\nب 2222\nج 3333", encoding="utf-8")
            masked = tokens(load_gt(path, verdicts=self.VERDICTS))
            raw = path.read_text(encoding="utf-8")
        self.assertIn("2222", masked)
        self.assertNotIn("1111", masked)
        self.assertNotIn("3333", masked)
        self.assertIn("1111", raw)

    def test_unmasked_load_returns_the_file_as_is(self):
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
            path = Path(tmp) / "d1.txt"
            path.write_text("الف 1111", encoding="utf-8")
            self.assertEqual(load_gt(path, masked=False, verdicts=self.VERDICTS), "الف 1111")


@unittest.skipUnless(VERDICTS_PATH.exists(), "number_verdicts.json is not in this checkout")
class AuditFile(unittest.TestCase):
    def test_every_entry_is_well_formed(self):
        entries = load_verdicts()
        self.assertGreater(len(entries), 0)
        for e in entries:
            self.assertEqual(set(e), {"doc", "gt", "ocr", "kind", "verdict"})
            self.assertIn(e["verdict"], {"ocr", "gt", "image"})
            self.assertIn(e["kind"], KINDS)
            self.assertTrue(e["gt"].isdigit())

    def test_documents_exist_in_the_eval_folder(self):
        if not EVAL_DATA_DIR.exists():
            self.skipTest("eval_data missing")
        names = {p.stem for p in EVAL_DATA_DIR.glob("*.txt")}
        self.assertTrue({e["doc"] for e in load_verdicts()} <= names)

    def test_judged_gt_numbers_are_really_in_the_ground_truth(self):
        if not EVAL_DATA_DIR.exists():
            self.skipTest("eval_data missing")
        for e in load_verdicts():
            gt = tokens((EVAL_DATA_DIR / f"{e['doc']}.txt").read_text(encoding="utf-8"))
            self.assertIn(e["gt"], gt, e)

    def test_masking_the_real_files_removes_exactly_the_judged_numbers(self):
        if not EVAL_DATA_DIR.exists():
            self.skipTest("eval_data missing")
        for doc in {e["doc"] for e in load_verdicts()}:
            path = EVAL_DATA_DIR / f"{doc}.txt"
            before = Counter(tokens(path.read_text(encoding="utf-8")))
            after = Counter(tokens(load_gt(path)))
            removed = before - after
            expected = masks_for(doc)
            for number, count in expected.items():
                self.assertEqual(removed[number], count, (doc, number))
            self.assertEqual(sum(removed.values()), sum(expected.values()), doc)


if __name__ == "__main__":
    unittest.main()
