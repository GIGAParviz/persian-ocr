import io
import json
import os
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

import numpy as np
from fastapi import HTTPException
from fastapi.testclient import TestClient

from persian_ocr.api.app import create_app
from persian_ocr.api.deps import API_KEY_ENV
from persian_ocr.config import TMP_DIR, PreprocessMode

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "invoice-sample.png"
RUN = "persian_ocr.api.routes.webapp.run_ocr"


def fake_result(*_args, **_kw):
    return {
        "time_sec": 1.5,
        "pages": [{
            "page": 1,
            "raw_text": "خام",
            "text": "متن",
            "text_dedup": "عنوان فاکتور\n| ۱ | ۲۰۰ |",
            "corrections": [],
            "review_queue": [{"kind": "reading_conflict", "input": "2200000", "output": "2200000", "status": "ambiguous_review", "candidates": ["3200000"]}],
            "low_confidence_lines": [],
            "tables_markdown": ["| ۱ | ۲۰۰ |"],
            "invoice": None,
        }],
    }


def uploads_on_disk() -> set:
    return {p.name for p in TMP_DIR.glob("upload_*")}


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(preload=False))

    def test_page_is_served_without_a_key_and_without_cdn(self):
        with patch.dict(os.environ, {API_KEY_ENV: "s3cret"}):
            res = self.client.get("/app")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])
        self.assertIn("/app/run", res.text)
        self.assertIn('id="prep"', res.text)
        self.assertIn('id="sourceView"', res.text)
        self.assertIn('id="editBtn"', res.text)
        self.assertIn('id="dlDocx"', res.text)
        self.assertIn('id="dlPdf"', res.text)
        self.assertNotIn("http://", res.text)
        self.assertNotIn("https://", res.text)

    def test_routes_are_not_in_the_api_schema(self):
        paths = set(self.client.get("/openapi.json").json()["paths"])
        self.assertFalse({p for p in paths if p.startswith("/app")})


@unittest.skipUnless(SAMPLE.exists(), "sample image missing")
class Run(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(preload=False))

    def post(self, name="فاکتور ۱.png", content=None, query=""):
        return self.client.post("/app/run" + query, files={"file": (name, SAMPLE.read_bytes() if content is None else content)})

    def test_response_has_viewer_data_and_downloads(self):
        with patch(RUN, side_effect=fake_result):
            body = self.post().json()
        doc = body["doc"]
        page = doc["pages"][0]
        self.assertEqual((doc["name"], doc["file"]), ("فاکتور ۱", "فاکتور ۱.png"))
        self.assertTrue(page["image"])
        self.assertIn("عنوان فاکتور", page["html"])
        self.assertIn("reading_conflict", page["notes"])
        self.assertEqual(page["stats"]["rev"], 1)
        self.assertIn("=== صفحه 1 ===", body["txt"])
        self.assertEqual(json.loads(body["json"])["file"], "فاکتور ۱.png")

    def test_options_reach_the_pipeline_with_lexicon_off_by_default(self):
        with patch(RUN, side_effect=fake_result) as run:
            self.post()
            self.post(query="?lexicon=true&max_pages=2&tables=false")
        self.assertEqual([c.args[1:] for c in run.call_args_list], [(False, 0, True), (True, 2, False)])

    def test_processed_image_and_mode_reach_web_ui(self):
        def fake_with_preview(*_args, **kwargs):
            self.assertEqual(kwargs["preprocess"], PreprocessMode.soft_light)
            self.assertIsNotNone(kwargs["on_page"])
            page = SimpleNamespace(lines=[SimpleNamespace(box=[2, 3, 35, 12], text="متن", conf=0.9)], tables=[])
            kwargs["on_page"](0, np.full((24, 40), 180, np.uint8), page)
            return fake_result()

        with patch(RUN, side_effect=fake_with_preview):
            page = self.post(query="?preprocess=soft_light").json()["doc"]["pages"][0]
        self.assertEqual(page["processed_size"], [40, 24])
        self.assertTrue(page["processed_image"])
        self.assertEqual(page["layout"]["size"], [40, 24])
        self.assertEqual(page["layout"]["items"][0]["text"], "متن")

    def test_invalid_preprocessing_mode_is_rejected(self):
        self.assertEqual(self.post(query="?preprocess=unknown").status_code, 422)

    def test_ground_truth_is_not_part_of_the_response(self):
        with patch(RUN, side_effect=fake_result):
            doc = self.post().json()["doc"]
        self.assertEqual(set(doc), {"name", "file", "time", "mismatch", "focus", "pages"})

    def test_unsupported_type_and_empty_file(self):
        self.assertEqual(self.post("notes.txt", b"hello").status_code, 415)
        self.assertEqual(self.post("empty.png", b"").status_code, 422)

    def test_pipeline_failure_is_reported_and_no_upload_is_left(self):
        before = uploads_on_disk()
        with patch(RUN, side_effect=HTTPException(status_code=422, detail="پردازش فایل ناموفق بود: x")):
            res = self.post()
        self.assertEqual(res.status_code, 422)
        self.assertIn("ناموفق", res.json()["detail"])
        self.assertEqual(uploads_on_disk(), before)

    def test_upload_is_deleted_after_success(self):
        before = uploads_on_disk()
        with patch(RUN, side_effect=fake_result):
            self.post()
        self.assertEqual(uploads_on_disk(), before)

    def test_key_is_required_when_configured(self):
        with patch.dict(os.environ, {API_KEY_ENV: "s3cret"}), patch(RUN, side_effect=fake_result):
            self.assertEqual(self.post().status_code, 401)
            res = self.client.post("/app/run", files={"file": ("a.png", SAMPLE.read_bytes())}, headers={"X-API-Key": "s3cret"})
            self.assertEqual(res.status_code, 200)


class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(preload=False))

    def test_exports_all_pages_as_valid_docx_with_persian_filename(self):
        pages = [{"page": i + 1, "text": f"ویرایش صفحه {i + 1}"} for i in range(5)]
        res = self.client.post("/app/export", json={"name": "گزارش.v2", "pages": pages})
        self.assertEqual(res.status_code, 200)
        self.assertIn("wordprocessingml", res.headers["content-type"])
        encoded = res.headers["content-disposition"].split("filename*=UTF-8''")[1]
        self.assertEqual(unquote(encoded), "گزارش.v2.docx")
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            text = "".join(ET.fromstring(zf.read("word/document.xml")).itertext())
        self.assertIn("ویرایش صفحه 1", text)
        self.assertIn("ویرایش صفحه 5", text)

    def test_empty_pages_rejected_and_key_enforced(self):
        self.assertEqual(self.client.post("/app/export", json={"name": "x", "pages": []}).status_code, 422)
        with patch.dict(os.environ, {API_KEY_ENV: "s3cret"}):
            payload = {"name": "x", "pages": [{"page": 1, "text": "سلام"}]}
            self.assertEqual(self.client.post("/app/export", json=payload).status_code, 401)
            self.assertEqual(self.client.post("/app/export", json=payload, headers={"X-API-Key": "s3cret"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
