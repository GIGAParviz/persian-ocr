import unittest
from pathlib import Path

from persian_ocr.config import MODEL_DIR, ROOT, PipelineConfig, setup_environment
from persian_ocr.engine import OcrEngine
from persian_ocr.pipeline import process_document


RECEIPT = ROOT / "file" / "test_data" / "bc2411b6-img__4294827.png"
INVOICE = ROOT / "file" / "test_data" / "2bd26e3e-img__4293952.png"
FAINT_PAYABLE = ROOT / "file" / "test_data" / "img_4291873_page_1.jpg"


@unittest.skipUnless(RECEIPT.exists() and INVOICE.exists() and (MODEL_DIR / "det.onnx").exists(), "OCR samples or model weights missing")
class ActualScans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_environment()
        cls.engine = OcrEngine.load(threads=2)

    def test_receipt_amount(self):
        page = process_document(self.engine, RECEIPT, PipelineConfig())["pages"][0]
        self.assertIn("مبلغ: 25,000,000 ریال", page["raw_text"])
        self.assertIn("مبلغ: 25,000,000 ریال", page["text_dedup"])
        self.assertNotIn("25,555,555", page["raw_text"])

    def test_invoice_payable(self):
        page = process_document(self.engine, INVOICE, PipelineConfig())["pages"][0]
        self.assertIn("قابل پرداخت: 3,192,200 ریال", page["raw_text"])
        self.assertIn("قابل پرداخت: 3,192,200 ریال", page["text_dedup"])
        self.assertTrue(any("قابل پرداخت: 3,192,200 ریال" in table for table in page["tables_markdown"]))
        self.assertTrue(any(item.get("context") == "قابل پرداخت: 3,192,200 ریال" for item in page["review_queue"]))

    @unittest.skipUnless(FAINT_PAYABLE.exists(), "Faint payable sample missing")
    def test_faint_payable_from_independent_readings(self):
        page = process_document(self.engine, FAINT_PAYABLE, PipelineConfig())["pages"][0]
        self.assertIn("قابل پرداخت: 11,100,000", page["raw_text"])
        self.assertIn("قابل پرداخت: 11,100,000", page["text_dedup"])
        self.assertIn("پرداخت شده: 11,100,000", page["raw_text"])
        self.assertTrue(any(item.get("kind") == "faint_payable_reread" and item.get("status") == "ambiguous_review" for item in page["review_queue"]))


if __name__ == "__main__":
    unittest.main()
