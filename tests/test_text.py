import unittest
from unittest.mock import patch

from persian_ocr.text import correct_by_checksum, is_valid_ir_iban, is_valid_legal_id, is_valid_nid, normalize, normalize_digits, postprocess_text

REAL_NIDS = ["3499838389", "0069938954", "0001384112", "6232625366"]
REAL_LEGAL_ID = "10392468456"


class Normalize(unittest.TestCase):
    def test_digits_all_systems(self):
        self.assertEqual(normalize_digits("۱۴۰۲/٠٣/15"), "1402/03/15")

    def test_arabic_letters_to_persian(self):
        self.assertEqual(normalize("كتاب يك"), "کتاب یک")

    def test_invisible_chars_removed(self):
        self.assertEqual(normalize("می\u200cخواهم"), "میخواهم")


class Checksums(unittest.TestCase):
    def test_real_national_ids_valid(self):
        for nid in REAL_NIDS:
            self.assertTrue(is_valid_nid(nid), nid)

    def test_persian_digits_accepted(self):
        self.assertTrue(is_valid_nid("۳۴۹۹۸۳۸۳۸۹"))

    def test_real_legal_id_valid(self):
        self.assertTrue(is_valid_legal_id(REAL_LEGAL_ID))

    def test_repeated_digits_rejected(self):
        self.assertFalse(is_valid_nid("1111111111"))

    def test_wrong_checksum_rejected(self):
        self.assertFalse(is_valid_nid("3499838380"))
        self.assertFalse(is_valid_legal_id("10814336154"))

    def test_iban_rejects_garbage(self):
        self.assertFalse(is_valid_ir_iban("IR123"))


class SafeCorrection(unittest.TestCase):
    def test_valid_untouched(self):
        self.assertEqual(correct_by_checksum("3499838389", "nid")["status"], "valid")

    def test_ctc_collapsed_digit_restored(self):
        res = correct_by_checksum("349838389", "nid")
        self.assertEqual((res["status"], res["output"]), ("auto_corrected", "3499838389"))

    def test_collapsed_zero_restored(self):
        res = correct_by_checksum("069938954", "nid")
        self.assertEqual((res["status"], res["output"]), ("auto_corrected", "0069938954"))

    def test_never_guesses_when_unfixable(self):
        self.assertEqual(correct_by_checksum("1234567891", "nid")["status"], "valid")
        res = correct_by_checksum("1234567892", "nid")
        self.assertIn(res["status"], ("invalid_review", "ambiguous_review", "auto_corrected"))
        if res["status"] != "auto_corrected":
            self.assertEqual(res["output"], "1234567892")

    def test_ambiguous_candidates_not_applied(self):
        res = correct_by_checksum("3499828389", "nid")
        if res["status"] == "ambiguous_review":
            self.assertEqual(res["output"], "3499828389")
            self.assertGreater(len(res["candidates"]), 1)

    def test_unknown_kind(self):
        self.assertEqual(correct_by_checksum("123", "zzz")["status"], "unknown_kind")

    def test_confusion_map_symmetric(self):
        from persian_ocr.text.correction import CONFUSION_MAP

        for a, alts in CONFUSION_MAP.items():
            for b in alts:
                self.assertIn(a, CONFUSION_MAP[b], f"{a}->{b} without {b}->{a}")

    def test_confused_digit_never_fixed_to_another_id(self):
        from persian_ocr.text.correction import CONFUSION_MAP

        for nid in REAL_NIDS + ["1960019392"]:
            for i, ch in enumerate(nid):
                for alt in CONFUSION_MAP.get(ch, ()):
                    misread = nid[:i] + alt + nid[i + 1:]
                    if is_valid_nid(misread):
                        continue
                    res = correct_by_checksum(misread, "nid")
                    if res["status"] == "auto_corrected":
                        self.assertEqual(res["output"], nid, misread)
                    else:
                        self.assertEqual(res["output"], misread)
                        self.assertIn(nid, res["candidates"], misread)

    def test_nine_read_as_four_not_replaced_by_other_id(self):
        res = correct_by_checksum("1960014392", "nid")
        self.assertNotEqual(res["output"], "1960014390")
        self.assertIn("1960019392", res["candidates"])


class Postprocess(unittest.TestCase):
    def test_context_national_id_fixed(self):
        out = postprocess_text("با شماره ملی ۳۴۹۸۳۸۳۸۹ به عنوان رئیس", use_lexicon=False)
        self.assertIn("3499838389", out["text"])
        self.assertEqual(len(out["corrections"]), 1)

    def test_jalali_date_missing_slash(self):
        out = postprocess_text("تاریخ ۱۴۰۲/۱۱۱۵", use_lexicon=False)
        self.assertIn("1402/11/15", out["text"])

    def test_capital_identity_repaired(self):
        text = "مبلغ ۴،۵۰۰ میلیارد ریال منقسم به ۴،۵۰۰،۰۰۰،۰۰۰ سهم با نام ۱،۰۰۰ ریالی"
        out = postprocess_text(text, use_lexicon=False)
        self.assertEqual(out["corrections"], [])

        broken = "مبلغ ۲۵۰۰۰ میلیارد ریال منقسم به ۲۵۰۰۰۲۰۰۰۰۰۰ سهم با نام ۱،۰۰۰ ریالی"
        fixed = postprocess_text(broken, use_lexicon=False)
        self.assertTrue(any(c["kind"] == "accounting_identity" for c in fixed["corrections"]))

    def test_correct_par_value_10000_untouched(self):
        text = "مبلغ 10 میلیارد ریال منقسم به 1000000 سهم با نام 10000 ریالی"
        out = postprocess_text(text, use_lexicon=False)
        self.assertIn("1000000 سهم با نام 10000 ریالی", out["text"])
        self.assertEqual(out["corrections"], [])

    def test_par_value_misread_as_10000_fixed_and_logged(self):
        text = "مبلغ 10 میلیارد ریال منقسم به 10000000 سهم با نام 10000 ریالی"
        out = postprocess_text(text, use_lexicon=False)
        self.assertIn("1,000 ریالی", out["text"])
        self.assertTrue(any(c.get("output") == "par=1,000" for c in out["corrections"]))

    def test_incomplete_day_goes_to_review_not_guessed(self):
        out = postprocess_text("مورخ 1402/053.", use_lexicon=False)
        self.assertNotIn("1402/05/30", out["text"])
        self.assertEqual(out["corrections"], [])
        review = [r for r in out["review_queue"] if r["kind"] == "jalali_date"]
        self.assertEqual(len(review), 1)
        self.assertIn("1402/05/30", review[0]["candidates"])
        self.assertIn("1402/05/03", review[0]["candidates"])

    def test_out_of_range_date_not_normalized(self):
        out = postprocess_text("تاریخ 1402.5.40", use_lexicon=False)
        self.assertNotIn("1402/05/40", out["text"])

    def test_extra_year_digit_logged(self):
        out = postprocess_text("تاریخ 14020/05/12", use_lexicon=False)
        self.assertIn("1402/05/12", out["text"])
        self.assertTrue(any(c["kind"] == "jalali_date" for c in out["corrections"]))

    def test_lexicon_off_adds_nothing(self):
        sample = {"entities": [{"triggers": ["آرمان تجارت نمونه"], "fields": {"postal_code": {"value": "1593613492", "context_patterns": [r"کد\s*پستی\s*\d+"]}}}]}
        with patch("persian_ocr.text.lexicon._load", return_value=sample):
            off = postprocess_text("شرکت آرمان تجارت نمونه کد پستی 1593", use_lexicon=False)
            on = postprocess_text("شرکت آرمان تجارت نمونه کد پستی 1593", use_lexicon=True)
        self.assertNotIn("تطبیق دیکشنری", off["text"])
        self.assertIn("postal_code=1593613492", on["text"])


if __name__ == "__main__":
    unittest.main()
