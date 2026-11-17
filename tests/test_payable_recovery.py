import unittest
from unittest.mock import patch

import numpy as np
from indra_ocr.pipeline import Line

from persian_ocr.vision.payable import recover_faint_payable


def sample_lines(total="مجموع :۱۱،۱۰۲,۴۰۰"):
    return [
        Line([841, 1121, 1235, 1156], total, 0.73),
        Line([293, 1117, 584, 1150], "تخفیف : 2,500", 0.87),
        Line([1006, 1168, 1299, 1209], "سهم سازمان :", 0.94),
        Line([354, 1165, 625, 1211], "قابل برداخت : و", 0.75),
        Line([272, 1165, 304, 1211], "و", 0.75),
        Line([167, 1165, 222, 1211], "۱۱", 0.75),
        Line([337, 1217, 627, 1261], "پرداخت شده : وو", 0.77),
        Line([187, 1217, 273, 1261], "۱۱۱", 0.77),
    ]


class FaintPayableRecovery(unittest.TestCase):
    def setUp(self):
        self.gray = np.zeros((1400, 1400), dtype=np.uint8)

    def test_agreement_preserves_other_row_text(self):
        lines = sample_lines()
        with patch("persian_ocr.vision.payable._read_number", side_effect=[(11100000, 0.56), (11100000, 0.53)]):
            recovered, review = recover_faint_payable(None, self.gray, lines)
        self.assertIn("قابل پرداخت: 11,100,000", [line.text for line in recovered])
        self.assertIn("پرداخت شده: 11,100,000", [line.text for line in recovered])
        self.assertIn("سهم سازمان :", [line.text for line in recovered])
        self.assertEqual(review[0]["status"], "ambiguous_review")

    def test_disagreeing_readings_do_not_replace_lines(self):
        lines = sample_lines()
        with patch("persian_ocr.vision.payable._read_number", side_effect=[(11100000, 0.56), (11800000, 0.61)]):
            recovered, review = recover_faint_payable(None, self.gray, lines)
        self.assertIs(recovered, lines)
        self.assertEqual(review, [])

    def test_arithmetic_mismatch_does_not_replace_lines(self):
        lines = sample_lines(total="مجموع :۱۲،۰۰۰،۰۰۰")
        with patch("persian_ocr.vision.payable._read_number", side_effect=[(11100000, 0.56), (11100000, 0.53)]):
            recovered, review = recover_faint_payable(None, self.gray, lines)
        self.assertIs(recovered, lines)
        self.assertEqual(review, [])


if __name__ == "__main__":
    unittest.main()
