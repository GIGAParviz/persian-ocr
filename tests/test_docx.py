import io
import unittest
import xml.etree.ElementTree as ET
import zipfile

from persian_ocr.report.docx import build_docx

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_document_xml(data: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            ET.fromstring(zf.read(name))
        return ET.fromstring(zf.read("word/document.xml"))


class DocxExport(unittest.TestCase):
    def test_valid_ooxml_with_rtl_paragraphs_and_tables(self):
        data = build_docx([{"page": 1, "text": "صورتحساب فروش\n| ردیف | مبلغ |\n| --- | --- |\n| ۱ | ۳,۲۰۰,۰۰۰ |\n| - | ۰ |"}])
        root = parse_document_xml(data)
        text = "".join(root.itertext())
        self.assertIn("صورتحساب فروش", text)
        self.assertIn("۳,۲۰۰,۰۰۰", text)
        self.assertNotIn("صفحه 1", text)
        self.assertTrue(root.findall(f".//{W_NS}bidi"))
        tables = root.findall(f".//{W_NS}tbl")
        self.assertEqual(len(tables), 1)
        self.assertTrue(tables[0].findall(f".//{W_NS}bidiVisual"))
        self.assertEqual(len(tables[0].findall(f".//{W_NS}tr")), 3)

    def test_multipage_has_page_labels_and_page_breaks(self):
        pages = [{"page": i + 1, "text": f"متن صفحه {i + 1}\n| ۱ | ۲۰۰ |"} for i in range(200)]
        data = build_docx(pages)
        root = parse_document_xml(data)
        breaks = root.findall(f".//{W_NS}pageBreakBefore")
        self.assertEqual(len(breaks), 199)
        texts = "".join(t.text or "" for t in root.findall(f".//{W_NS}t"))
        self.assertIn("صفحه 1", texts)
        self.assertIn("صفحه 200", texts)
        self.assertIn("متن صفحه 200", texts)

    def test_control_characters_and_xml_specials_do_not_break_xml(self):
        data = build_docx([{"page": 1, "text": "متن \x00\x07 با <tag> & \"quote\""}])
        root = parse_document_xml(data)
        texts = "".join(t.text or "" for t in root.findall(f".//{W_NS}t"))
        self.assertIn('<tag> & "quote"', texts)


if __name__ == "__main__":
    unittest.main()
