import unittest

from evaluation.metrics import aggregate, document_metrics, has_invalid_id, tokens


class Tokens(unittest.TestCase):
    def test_numbers_and_words_split(self):
        self.assertEqual(tokens("مبلغ ۳۵۰,۰۰۰ ریال MECH-1"), ["مبلغ", "350000", "ریال", "MECH", "1"])


class DocumentMetrics(unittest.TestCase):
    GT = "شرکت نمونه\nمبلغ ۳۵۰۰۰۰\nتاریخ ۱۴۰۳"

    def test_perfect_output(self):
        m = document_metrics(self.GT, self.GT)
        self.assertEqual((m["word_acc"], m["wer_ordered"], m["cer"], m["ser"], m["num_acc"]), (1.0, 0.0, 0.0, 0.0, 1.0))

    def test_empty_output(self):
        m = document_metrics(self.GT, "")
        self.assertEqual((m["word_acc"], m["ser"], m["num_acc"]), (0.0, 1.0, 0.0))

    def test_reordering_hurts_ordered_but_not_orderfree(self):
        shuffled = "تاریخ ۱۴۰۳\nشرکت نمونه\nمبلغ ۳۵۰۰۰۰"
        m = document_metrics(self.GT, shuffled)
        self.assertGreater(m["wer_ordered"], 0)
        self.assertEqual(m["wer_free"], 0.0)
        self.assertEqual(m["word_acc"], 1.0)

    def test_one_wrong_digit_fails_whole_line_in_ser(self):
        m = document_metrics(self.GT, "شرکت نمونه\nمبلغ ۳۵۰۰۰۱\nتاریخ ۱۴۰۳")
        self.assertAlmostEqual(m["ser"], 1 / 3)
        self.assertLess(m["num_acc"], 1.0)

    def test_extra_words_lower_precision_only(self):
        m = document_metrics(self.GT, self.GT + "\nمهر امضا اضافه")
        self.assertEqual(m["word_acc"], 1.0)
        self.assertLess(m["word_prec"], 1.0)


class Adjusted(unittest.TestCase):
    def test_invalid_id_line_detected(self):
        self.assertTrue(has_invalid_id("شناسه ملی: ۱۰۸۱۴۳۳۶۱۵۴"))
        self.assertFalse(has_invalid_id("شناسه ملی: ۱۰۳۹۲۴۶۸۴۵۶"))

    def test_adjusted_ser_skips_gt_errors(self):
        gt = "شناسه ملی ۱۰۸۱۴۳۳۶۱۵۴\nتاریخ ۱۴۰۳"
        m = document_metrics(gt, "تاریخ ۱۴۰۳")
        self.assertEqual(m["ser_adj"], 0.0)
        self.assertEqual(m["ser"], 0.5)


    def test_amounts_and_phones_are_not_id_errors(self):
        self.assertFalse(has_invalid_id("مبلغ ۱۲,۵۰۰,۰۰۰,۰۰۰ ریال"))
        self.assertFalse(has_invalid_id("موبایل ۰۹۱۲۱۲۳۴۵۶۷"))
        self.assertFalse(has_invalid_id("کدپستی ۱۳۵۷۹۲۴۶۸۰"))

    def test_hypothesis_tokens_used_once_in_ser(self):
        gt = "ریال ۱۱۱۱\nریال ۲۲۲۲\nریال ۳۳۳۳"
        m = document_metrics(gt, "ریال ۱۱۱۱ ۲۲۲۲ ۳۳۳۳")
        self.assertAlmostEqual(m["ser"], 2 / 3)

    def test_punctuation_is_not_a_word_error(self):
        m = document_metrics("سلام دنیا", "سلام، دنیا؟")
        self.assertEqual((m["word_acc"], m["word_prec"]), (1.0, 1.0))


class Aggregate(unittest.TestCase):
    def test_micro_average_weights_by_size(self):
        big = document_metrics("الف ب ج د ه و ز ح ط ی", "الف ب ج د ه و ز ح ط ی")
        small = document_metrics("کیان", "")
        agg = aggregate([big, small])
        self.assertAlmostEqual(agg["word_acc"], 10 / 11)

    def test_errors_do_not_cancel_across_documents(self):
        missing = document_metrics("الف ب", "")
        extra = document_metrics("ج", "ج د ه")
        agg = aggregate([missing, extra])
        self.assertAlmostEqual(agg["wer_free"], (2 + 2) / 3)

    def test_empty_inputs_do_not_crash(self):
        self.assertEqual(aggregate([])["word_acc"], 0)
        self.assertEqual(aggregate([document_metrics("الف", "")])["word_prec"], 0)


class Fields(unittest.TestCase):
    def test_value_not_assembled_across_lines(self):
        from evaluation.fields import evaluate_fields

        self.assertEqual(evaluate_fields([{"name": "x", "value": "1234"}], "5612\n3478")["matched"], 0)

    def test_value_not_found_inside_longer_number(self):
        from evaluation.fields import evaluate_fields

        self.assertEqual(evaluate_fields([{"name": "x", "value": "1234"}], "کد 512345")["matched"], 0)

    def test_separator_variants_still_match(self):
        from evaluation.fields import evaluate_fields

        self.assertEqual(evaluate_fields([{"name": "d", "value": "1402/05/12"}], "تاریخ ۱۴۰۲.۰۵.۱۲")["matched"], 1)


if __name__ == "__main__":
    unittest.main()
