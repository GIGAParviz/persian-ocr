import unittest

import indra_ocr.pipeline as indra_pipeline
import numpy as np

from persian_ocr.engine import MIN_REC_WIDTH, pad_batch_min_width


class PadBatch(unittest.TestCase):
    def test_indra_uses_the_min_width_padding(self):
        self.assertIs(indra_pipeline.pad_batch, pad_batch_min_width)

    def test_narrow_batch_is_padded_with_zeros_to_min_width(self):
        line = np.ones((48, 8), np.float32)
        arr, widths = pad_batch_min_width([line])
        self.assertEqual(arr.shape, (1, 1, 48, MIN_REC_WIDTH))
        self.assertEqual(widths.tolist(), [8])
        self.assertTrue((arr[0, 0, :, :8] == 1).all() and (arr[0, 0, :, 8:] == 0).all())

    def test_wide_batch_is_unchanged(self):
        lines = [np.ones((48, 70), np.float32), np.ones((48, 20), np.float32)]
        arr, widths = pad_batch_min_width(lines)
        self.assertEqual(arr.shape, (2, 1, 48, 72))
        self.assertEqual(widths.tolist(), [70, 20])


if __name__ == "__main__":
    unittest.main()
