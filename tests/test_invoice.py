import unittest

from persian_ocr.invoice import parse_invoice, reconcile_document
from persian_ocr.invoice.equations import verify_item
from persian_ocr.invoice.numbers import digit_edit_distance, is_close, parse_number
from persian_ocr.tables import Cell, Table


class Numbers(unittest.TestCase):
    def test_parse_number_separators(self):
        self.assertEqual(parse_number("۷۰,۰۰۰,۰۰۰"), 70_000_000)
        self.assertEqual(parse_number("350٬000٬000"), 350_000_000)

    def test_grouped_separators_any_kind(self):
        self.assertEqual(parse_number("۷۰٫۰۰۰٫۰۰۰"), 70_000_000)
        self.assertEqual(parse_number("12.500.000"), 12_500_000)
        self.assertEqual(parse_number("350/000/000"), 350_000_000)
        self.assertEqual(parse_number("350,000.000"), 350_000_000)

    def test_decimals_and_dates_rejected(self):
        self.assertIsNone(parse_number("۲٫۵"))
        self.assertIsNone(parse_number("1234.5"))
        self.assertIsNone(parse_number("2.5"))
        self.assertIsNone(parse_number("1402/05/12"))

    def test_dots_mean_zero(self):
        self.assertEqual(parse_number("•"), 0)
        self.assertEqual(parse_number("."), 0)

    def test_text_is_none(self):
        self.assertIsNone(parse_number("عدد"))
        self.assertIsNone(parse_number(""))

    def test_close_means_one_edit(self):
        self.assertEqual(digit_edit_distance("350", "250"), 1)
        self.assertTrue(is_close(250_000_000, 350_000_000))
        self.assertFalse(is_close(150_000_000, 350_000_000 - 100))


class RowEquations(unittest.TestCase):
    def test_amount_misread_fixed_from_qty_and_unit(self):
        item = {"qty": 5, "unit_price": 70_000_000, "amount": 250_000_000, "tax": 35_000_000, "net": 385_000_000}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual(item["amount"], 350_000_000)
        self.assertEqual(item["unit_price"], 70_000_000)
        self.assertEqual(checks[0]["status"], "corrected")

    def test_ambiguous_row_fix_not_guessed(self):
        item = {"qty": 5, "unit_price": 70_000_000, "amount": 250_000_000}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual((item["unit_price"], item["amount"]), (70_000_000, 250_000_000))
        self.assertEqual(checks[0]["status"], "mismatch")
        self.assertEqual(len(checks[0]["candidates"]), 2)

    def test_misread_qty_fixed_when_net_supports_it(self):
        item = {"qty": 3, "unit_price": 1000, "amount": 2000, "tax": 200, "net": 2200}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual((item["qty"], item["amount"]), (2, 2000))

    def test_misread_qty_without_evidence_not_guessed(self):
        item = {"qty": 3, "unit_price": 1000, "amount": 2000}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual((item["qty"], item["amount"]), (3, 2000))
        self.assertEqual(checks[0]["status"], "mismatch")

    def test_vat_rounds_half_up(self):
        for amount, tax in ((12_345, 1_235), (1_000_050, 90_005)):
            item = {"amount": amount, "tax": tax, "net": amount + tax}
            checks: list = []
            verify_item(item, checks, 1)
            self.assertEqual(item["tax"], tax)
            self.assertTrue(all(c["status"] == "ok" for c in checks), checks)

    def test_consistent_row_unchanged(self):
        item = {"qty": 2, "unit_price": 33_919_000, "amount": 67_838_000, "net": 74_621_800}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual(item["net"], 74_621_800)
        self.assertTrue(all(c["status"] == "ok" for c in checks))

    def test_unrelated_numbers_flagged_not_changed(self):
        item = {"qty": 2, "unit_price": 1_000_000, "amount": 9_999_999}
        checks: list = []
        verify_item(item, checks, 1)
        self.assertEqual(item["amount"], 9_999_999)
        self.assertEqual(checks[0]["status"], "mismatch")


def _table(rows: list[list[str]], col_width: int = 100) -> Table:
    table = Table(box=(0, 0, col_width * len(rows[0]), 40 * len(rows)))
    for ri, row in enumerate(rows):
        table.rows.append([Cell(box=(ci * col_width, ri * 40, (ci + 1) * col_width, ri * 40 + 38), text=t) for ci, t in enumerate(row)])
    return table


class Parse(unittest.TestCase):
    HEADER = ["تعداد", "مبلغ واحد", "مبلغ کل", "مبلغ کل پس از تخفیف", "جمع مالیات و عوارض", "خالص فاکتور"]

    def test_non_invoice_table_is_none(self):
        self.assertIsNone(parse_invoice(_table([["نام", "پدر"], ["علی", "رضا"]])))

    def test_single_page_invoice(self):
        table = _table([
            self.HEADER,
            ["5", "70,000,000", "350,000,000", "350,000,000", "35,000,000", "385,000,000"],
            ["جمع کل", "", "350,000,000", "350,000,000", "35,000,000", "385,000,000"],
        ])
        inv = parse_invoice(table)
        self.assertEqual(len(inv["items"]), 1)
        self.assertEqual(inv["items"][0]["net"], 385_000_000)
        self.assertEqual(inv["check_summary"]["mismatch"], 0)

    def test_misread_total_row_corrected_by_page_sum(self):
        table = _table([
            self.HEADER,
            ["5", "70,000,000", "350,000,000", "350,000,000", "35,000,000", "385,000,000"],
            ["جمع کل", "", "250,000,000", "350,000,000", "35,000,000", "385,000,000"],
        ])
        inv = parse_invoice(table)
        self.assertEqual(inv["totals"]["sum_amount"], 350_000_000)

    def test_document_reconcile_closes_deferred_checks(self):
        def page(row_net: str, total_net: str | None):
            rows = [self.HEADER, ["1", "1,000,000", "1,000,000", "1,000,000", "100,000", row_net]]
            if total_net:
                rows.append(["جمع کل", "", "", "", "", total_net])
            return parse_invoice(_table(rows))

        first, second = page("1,100,000", None), page("1,100,000", "2,200,000")
        reconcile_document([first, second])
        statuses = [c["status"] for c in second["checks"] if "sum(net)" in c["check"]]
        self.assertEqual(statuses, ["ok"])


if __name__ == "__main__":
    unittest.main()
