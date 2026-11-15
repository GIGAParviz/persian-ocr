import io
import os
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from fastapi.testclient import TestClient

from persian_ocr.api.app import create_app
from persian_ocr.api.deps import API_KEY_ENV
from persian_ocr.api.downloads import content_disposition, output_stem, zip_bundle
from persian_ocr.api.uploads import MAX_UPLOAD_ENV
from persian_ocr.config import MODEL_DIR, TMP_DIR

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "invoice-sample.png"


def uploads_on_disk() -> set:
    return {p.name for p in TMP_DIR.glob("upload_*")}


class ApiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(preload=False))


class Health(ApiCase):
    def test_health_fields(self):
        body = self.client.get("/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual({"version", "model_dir", "model_loaded", "auth_required", "max_upload_mb"} <= set(body), True)


class Docs(ApiCase):
    def test_swagger_ui_uses_local_assets(self):
        page = self.client.get("/docs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/static/swagger/swagger-ui-bundle.js", page.text)
        self.assertNotIn("cdn.jsdelivr", page.text)
        self.assertEqual(self.client.get("/static/swagger/swagger-ui-bundle.js").status_code, 200)
        self.assertEqual(self.client.get("/static/swagger/swagger-ui.css").status_code, 200)

    def test_openapi_lists_all_endpoints(self):
        paths = set(self.client.get("/openapi.json").json()["paths"])
        expected = {"/health", "/ocr", "/ocr/text", "/ocr/review", "/ocr/download", "/validate/national-id", "/validate/legal-id", "/validate/iban", "/validate/postal-code", "/text/postprocess", "/text/normalize", "/invoice/verify-item"}
        self.assertEqual(paths, expected)

    def test_root_redirects_to_docs(self):
        res = self.client.get("/", follow_redirects=False)
        self.assertIn(res.status_code, (302, 307))
        self.assertEqual(res.headers["location"], "/docs")


class Validation(ApiCase):
    def post(self, path, value):
        return self.client.post(path, json={"value": value}).json()

    def test_valid_national_id_with_persian_digits(self):
        body = self.post("/validate/national-id", "۳۴۹۹۸۳۸۳۸۹")
        self.assertEqual((body["valid"], body["status"], body["output"]), (True, "valid", "3499838389"))

    def test_collapsed_digit_is_restored(self):
        body = self.post("/validate/national-id", "349838389")
        self.assertEqual((body["valid"], body["status"], body["output"]), (False, "auto_corrected", "3499838389"))

    def test_never_guesses_when_ambiguous(self):
        body = self.post("/validate/national-id", "1234567892")
        self.assertEqual(body["status"], "ambiguous_review")
        self.assertEqual(body["output"], "1234567892")
        self.assertGreater(len(body["candidates"]), 1)

    def test_legal_id(self):
        self.assertTrue(self.post("/validate/legal-id", "10392468456")["valid"])
        self.assertFalse(self.post("/validate/legal-id", "10814336154")["valid"])

    def test_iban_and_postal(self):
        self.assertFalse(self.post("/validate/iban", "IR123")["valid"])
        self.assertTrue(self.post("/validate/postal-code", "1357924680")["valid"])
        self.assertFalse(self.post("/validate/postal-code", "0123456789")["valid"])

    def test_missing_value_is_validation_error(self):
        self.assertEqual(self.client.post("/validate/national-id", json={}).status_code, 422)


class TextRules(ApiCase):
    def test_postprocess_fixes_id_and_date(self):
        res = self.client.post("/text/postprocess", json={"text": "با شماره ملی ۳۴۹۸۳۸۳۸۹ مورخ ۱۴۰۵/۰۳۱۷"}).json()
        self.assertIn("3499838389", res["text"])
        self.assertIn("1405/03/17", res["text"])
        self.assertEqual(len(res["corrections"]), 2)

    def test_lexicon_is_opt_in(self):
        sample = {"entities": [{"triggers": ["آرمان تجارت نمونه"], "fields": {"postal_code": {"value": "1593613492", "context_patterns": [r"کد\s*پستی\s*\d+"]}}}]}
        text = "شرکت آرمان تجارت نمونه کد پستی ۱۵۹۳"
        with patch("persian_ocr.text.lexicon._load", return_value=sample):
            off = self.client.post("/text/postprocess", json={"text": text}).json()
            on = self.client.post("/text/postprocess", json={"text": text, "use_lexicon": True}).json()
        self.assertNotIn("تطبیق دیکشنری", off["text"])
        self.assertIn("postal_code=1593613492", on["text"])

    def test_normalize_digit_switch(self):
        on = self.client.post("/text/normalize", json={"text": "كتاب يك ۱۲۳"}).json()["text"]
        off = self.client.post("/text/normalize", json={"text": "كتاب يك ۱۲۳", "latin_digits": False}).json()["text"]
        self.assertEqual((on, off), ("کتاب یک 123", "کتاب یک ۱۲۳"))


class InvoiceRow(ApiCase):
    def test_amount_is_corrected_from_qty_and_unit(self):
        body = self.client.post("/invoice/verify-item", json={"qty": 5, "unit_price": 70000000, "amount": 250000000, "tax": 35000000, "net": 385000000}).json()
        self.assertEqual(body["item"]["amount"], 350000000)
        self.assertEqual(body["check_summary"]["corrected"], 1)
        self.assertEqual(body["check_summary"]["mismatch"], 0)

    def test_unrelated_numbers_are_flagged_not_changed(self):
        body = self.client.post("/invoice/verify-item", json={"qty": 2, "unit_price": 1000000, "amount": 9999999}).json()
        self.assertEqual(body["item"]["amount"], 9999999)
        self.assertEqual(body["check_summary"]["mismatch"], 1)


class ApiKey(ApiCase):
    def test_open_when_no_key_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(API_KEY_ENV, None)
            self.assertEqual(self.client.post("/validate/postal-code", json={"value": "1357924680"}).status_code, 200)

    def test_protected_when_key_configured(self):
        with patch.dict(os.environ, {API_KEY_ENV: "s3cret"}):
            body = {"value": "1357924680"}
            self.assertEqual(self.client.post("/validate/postal-code", json=body).status_code, 401)
            self.assertEqual(self.client.post("/validate/postal-code", json=body, headers={"X-API-Key": "wrong"}).status_code, 401)
            self.assertEqual(self.client.post("/validate/postal-code", json=body, headers={"X-API-Key": "s3cret"}).status_code, 200)
            self.assertEqual(self.client.post("/ocr", files={"file": ("a.pdf", b"%PDF-1.4")}).status_code, 401)
            self.assertEqual(self.client.get("/health").status_code, 200)
            self.assertTrue(self.client.get("/health").json()["auth_required"])


class Uploads(ApiCase):
    def post_file(self, name, content, path="/ocr"):
        return self.client.post(path, files={"file": (name, content)})

    def test_unsupported_type(self):
        self.assertEqual(self.post_file("notes.txt", b"hello").status_code, 415)

    def test_empty_file(self):
        self.assertEqual(self.post_file("empty.pdf", b"").status_code, 422)

    def test_fake_pdf(self):
        self.assertEqual(self.post_file("fake.pdf", b"not a pdf at all").status_code, 422)

    def test_size_limit(self):
        with patch.dict(os.environ, {MAX_UPLOAD_ENV: "0.00001"}):
            self.assertEqual(self.post_file("big.pdf", b"%PDF-1.4" + b"x" * 5000).status_code, 413)

    def test_missing_file_field(self):
        self.assertEqual(self.client.post("/ocr", files={"other": ("a.pdf", b"%PDF")}).status_code, 422)

    def test_no_upload_left_on_disk(self):
        before = uploads_on_disk()
        for name, content in (("a.txt", b"x"), ("b.pdf", b""), ("c.pdf", b"junk"), ("d.pdf", b"%PDF-1.4 broken")):
            self.post_file(name, content)
        self.assertEqual(uploads_on_disk(), before)


class DownloadNames(unittest.TestCase):
    def stem(self, filename):
        return output_stem(SimpleNamespace(filename=filename))

    def test_stem_drops_extension_only(self):
        self.assertEqual(self.stem("18185.pdf"), "18185")
        self.assertEqual(self.stem("a.b.c.PNG"), "a.b.c")

    def test_persian_stem_is_kept(self):
        self.assertEqual(self.stem("پیوست 14.pdf"), "پیوست 14")

    def test_unsafe_characters_and_paths_are_neutralised(self):
        self.assertEqual(self.stem("../../etc/passwd.pdf"), "passwd")
        self.assertNotIn('"', self.stem('a"b<c>.pdf'))
        self.assertEqual(self.stem(""), "document")
        self.assertEqual(self.stem(None), "document")

    def test_ascii_header(self):
        self.assertEqual(content_disposition("18185.txt"), "attachment; filename=\"18185.txt\"; filename*=UTF-8''18185.txt")

    def test_persian_header_roundtrips(self):
        header = content_disposition("پیوست 14.txt")
        self.assertTrue(header.isascii())
        encoded = header.split("filename*=UTF-8''")[1]
        self.assertEqual(unquote(encoded), "پیوست 14.txt")

    def test_zip_entries_share_the_stem(self):
        files = {"txt": ("x.txt", b"a"), "json": ("x.json", b"{}")}
        with zipfile.ZipFile(io.BytesIO(zip_bundle(files))) as archive:
            self.assertEqual(archive.namelist(), ["x.txt", "x.json"])


class TablesSwitch(ApiCase):
    def test_tables_flag_reaches_pipeline_config(self):
        result = {"file": "a.png", "time_sec": 0.0, "pages": []}
        with patch("persian_ocr.api.routes.ocr.get_engine"), patch("persian_ocr.api.routes.ocr.process_document", return_value=result) as run:
            self.client.post("/ocr/text", files={"file": ("a.png", b"x")})
            self.client.post("/ocr/text?tables=false", files={"file": ("a.png", b"x")})
        self.assertEqual([c.args[2].tables for c in run.call_args_list], [True, False])


@unittest.skipUnless(SAMPLE.exists() and (MODEL_DIR / "det.onnx").exists(), "sample image or model weights missing")
class DownloadEndToEnd(ApiCase):
    def download(self, filename, fmt):
        return self.client.post(f"/ocr/download?format={fmt}&lexicon=false", files={"file": (filename, SAMPLE.read_bytes())})

    def test_each_format_is_named_after_the_input(self):
        for fmt in ("txt", "json", "html"):
            res = self.download("scan 7.PNG", fmt)
            self.assertEqual(res.status_code, 200, res.text[:200])
            self.assertIn(f'filename="scan 7.{fmt}"', res.headers["content-disposition"])
            self.assertTrue(res.headers["content-disposition"].startswith("attachment"))

    def test_zip_contains_three_files_with_the_input_name(self):
        res = self.download("scan 7.PNG", "zip")
        self.assertIn('filename="scan 7.zip"', res.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["scan 7.html", "scan 7.json", "scan 7.txt"])

    def test_persian_name_header(self):
        res = self.download("فاکتور ۱.png", "txt")
        encoded = res.headers["content-disposition"].split("filename*=UTF-8''")[1]
        self.assertEqual(unquote(encoded), "فاکتور ۱.txt")

    def test_bad_format_is_rejected_and_nothing_is_left(self):
        before = uploads_on_disk()
        self.assertEqual(self.download("a.png", "pdf").status_code, 422)
        self.assertEqual(self.client.post("/ocr/download", files={"file": ("a.txt", b"x")}).status_code, 415)
        self.assertEqual(uploads_on_disk(), before)


if __name__ == "__main__":
    unittest.main()
