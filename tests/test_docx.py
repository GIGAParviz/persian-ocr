import io
import unittest
import xml.etree.ElementTree as ET
import zipfile

import pypdfium2 as pdfium

from persian_ocr.report.docx import build_docx
from persian_ocr.report.pdf import build_pdf

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_document_xml(data: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            ET.fromstring(zf.read(name))
        return ET.fromstring(zf.read("word/document.xml"))


def sample_layout():
    return {
        "size": [1760, 2500],
        "tables": [[80, 300, 1680, 480]],
        "cells": [
            [80, 300, 1680, 360],
            [880, 360, 1680, 480],
            [80, 360, 880, 480],
        ],
        "items": [
            {"box": [550, 80, 1210, 130], "text": "صورتحساب فروش", "conf": 0.96, "source": "line"},
            {"box": [1250, 180, 1680, 220], "text": "شماره سریال: ۳۱۸۷", "conf": 0.95, "source": "line"},
            {"box": [80, 180, 450, 220], "text": "تاریخ: 1405/08/19", "conf": 0.95, "source": "line"},
            {"box": [1200, 310, 1660, 350], "text": "مشخصات فروشنده", "conf": 0.96, "source": "cell"},
            {"box": [900, 370, 1660, 410], "text": "نام: شرکت نمونه", "conf": 0.95, "source": "cell"},
            {"box": [100, 370, 860, 410], "text": "مبلغ: ١٢,۵٠٠,٠٠٠", "conf": 0.94, "source": "cell"},
        ],
    }


class DocxExport(unittest.TestCase):
    def test_valid_ooxml_with_rtl_paragraphs_and_tables(self):
        data = build_docx([{"page": 1, "text": "صورتحساب فروش\n| ردیف | مبلغ |\n| --- | --- |\n| ۱ | ۳,۲۰۰,۰۰۰ |\n| - | ۰ |"}])
        root = parse_document_xml(data)
        text = "".join(root.itertext())
        self.assertIn("صورتحساب فروش", text)
        self.assertIn("۳,۲۰۰,۰۰۰", text)
        self.assertTrue(root.findall(f".//{W_NS}bidi"))
        tables = root.findall(f".//{W_NS}tbl")
        self.assertEqual(len(tables), 1)
        self.assertTrue(tables[0].findall(f".//{W_NS}bidiVisual"))
        self.assertEqual(len(tables[0].findall(f".//{W_NS}tr")), 3)

    def test_layout_preserves_2d_structure_and_valid_xml_order(self):
        data = build_docx([{"page": 1, "text": "", "layout": sample_layout()}])
        root = parse_document_xml(data)
        tables = root.findall(f".//{W_NS}tbl")
        # 1 borderless grid for the 2-column header row + 1 bordered table for cells
        self.assertEqual(len(tables), 2)
        self.assertTrue(root.findall(f".//{W_NS}gridSpan"))
        for el in root.findall(f".//{W_NS}sectPr"):
            names = [c.tag.split("}")[-1] for c in el]
            self.assertLess(names.index("bidi"), names.index("docGrid"))
        for el in root.findall(f".//{W_NS}tblPr"):
            names = [c.tag.split("}")[-1] for c in el]
            self.assertLess(names.index("bidiVisual"), names.index("tblW"))
        for el in root.findall(f".//{W_NS}pPr"):
            names = [c.tag.split("}")[-1] for c in el]
            if "bidi" in names and "jc" in names:
                self.assertLess(names.index("bidi"), names.index("jc"))

    def test_landscape_layout_uses_landscape_section(self):
        layout = sample_layout()
        layout["size"] = [2500, 1760]
        root = parse_document_xml(build_docx([{"page": 1, "text": "", "layout": layout}]))
        pg_sz = root.find(f".//{W_NS}pgSz")
        self.assertGreater(int(pg_sz.get(f"{W_NS}w")), int(pg_sz.get(f"{W_NS}h")))

    def test_control_characters_and_xml_specials_do_not_break_xml(self):
        data = build_docx([{"page": 1, "text": "متن \x00\x07 با <tag> & \"quote\""}])
        root = parse_document_xml(data)
        self.assertIn('<tag> & "quote"', "".join(root.itertext()))


class PdfExport(unittest.TestCase):
    def test_layout_pdf_builds_all_pages_with_persian_text(self):
        pages = [{"page": i + 1, "text": "", "layout": sample_layout()} for i in range(20)]
        data = build_pdf(pages)
        self.assertTrue(data.startswith(b"%PDF-"))
        doc = pdfium.PdfDocument(data)
        try:
            self.assertEqual(len(doc), 20)
            extracted = doc[0].get_textpage().get_text_range()
            self.assertIn("صورتحساب", extracted)
            self.assertIn("۱۲", extracted)
        finally:
            doc.close()

    def test_plain_fallback_handles_tables_without_layout(self):
        data = build_pdf([{"page": 1, "text": "عنوان\n| ۱ | ۲۰۰ |", "layout": None}])
        doc = pdfium.PdfDocument(data)
        try:
            self.assertEqual(len(doc), 1)
            self.assertIn("عنوان", doc[0].get_textpage().get_text_range())
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
