import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from persian_ocr.api.app import create_app
from persian_ocr.api.deps import API_KEY_ENV
from persian_ocr.config import TMP_DIR

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


if __name__ == "__main__":
    unittest.main()
