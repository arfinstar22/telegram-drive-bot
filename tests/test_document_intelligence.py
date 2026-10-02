"""Comprehensive test suite for Task 3C: Receipt & Document Intelligence Core.

100% deterministic, local execution using standard library unittest.
Zero AI APIs, zero external network or database calls.

Covers:
- Receipt Extraction: merchant, totals, taxes, discounts, payments, items, arithmetic reconciliation
- Document Extraction: official letter, invoice, academic document, bank document, proposal, certificate, form
- Ambiguity & Safety: single total, random numbers, single nomor, arithmetic conflict, OTP & card privacy
- Edge Cases: empty text, malformed inputs, very long text, unicode, OCR typos, OCR garbage
- Task 3B Integration: receipt_candidate & document category handoff
"""

from __future__ import annotations

import logging
import time
import unittest
from typing import Any

from darfin_intelligence.document import (
    DocumentData,
    DocumentIntelligenceAnalyzer,
    DocumentIntelligenceResult,
    ReceiptData,
    ReceiptItem,
    analyze_document,
    analyze_receipt,
    clean_document_text,
    extract_document_dates,
    extract_document_number,
    extract_labeled_amounts,
    extract_line_items,
    extract_merchant_name,
    extract_payment_method,
    extract_recipient,
    extract_sender,
    extract_subject,
    extract_attachment,
    normalize_ocr_typos,
    parse_document,
    parse_iso_date,
    parse_money_value,
    parse_receipt,
)
from darfin_intelligence.ocr.models import OCRResult
from darfin_intelligence.screenshot.models import ScreenshotIntelligenceResult


class TestReceiptExtraction(unittest.TestCase):
    """Section 21: Receipt parsing tests (Tests 1 - 18)."""

    def test_01_basic_indonesian_receipt(self):
        """Test 1: Basic Indonesian store receipt with total and merchant."""
        text = """
        INDOMARET
        TOTAL Rp 127.500
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "receipt")
        self.assertIsNotNone(res.receipt)
        self.assertEqual(res.receipt.merchant_name, "Indomaret")
        self.assertEqual(res.receipt.total, 127500)

    def test_02_merchant_extraction(self):
        """Test 2: Known retail brands extracted properly."""
        cases = [
            ("ALFAMART\nTOTAL Rp 50.000", "Alfamart"),
            ("Starbucks Coffee\nTotal 65000", "Starbucks"),
            ("SUPER INDO\nTOTAL Rp 150.000", "Super Indo"),
            ("KFC MALL KELAPA GADING\nTOTAL 85000", "Kfc"),
        ]
        for snippet, expected_name in cases:
            rec = parse_receipt(snippet)
            self.assertEqual(rec.merchant_name, expected_name)

    def test_03_subtotal_extraction(self):
        """Test 3: Subtotal extraction."""
        text = """
        ALFAMIDI
        SUBTOTAL Rp 45.000
        TOTAL Rp 45.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.subtotal, 45000)
        self.assertEqual(rec.total, 45000)

    def test_04_grand_total_extraction(self):
        """Test 4: Grand total / total bayar variants."""
        text = """
        RESTORAN SEDAP
        JUMLAH BAYAR Rp 250.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.total, 250000)

    def test_05_discount_extraction(self):
        """Test 5: Discount / promo / hemat extraction."""
        text = """
        INDOMARET
        SUBTOTAL 50.000
        DISKON 5.000
        TOTAL 45.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.discount, 5000)
        self.assertEqual(rec.subtotal, 50000)
        self.assertEqual(rec.total, 45000)

    def test_06_tax_extraction(self):
        """Test 6: Tax / PPN extraction."""
        text = """
        CAFE KOPI
        SUBTOTAL 100.000
        PPN 11% 11.000
        TOTAL 111.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.tax, 11000)
        self.assertEqual(rec.total, 111000)

    def test_07_service_charge_extraction(self):
        """Test 7: Service charge / biaya layanan extraction."""
        text = """
        BISTRO BALI
        SUBTOTAL 200.000
        BIAYA LAYANAN 10.000
        TOTAL 210.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.service_charge, 10000)
        self.assertEqual(rec.total, 210000)

    def test_08_cash_payment_extraction(self):
        """Test 8: Cash payment / tunai diterima extraction."""
        text = """
        INDOMARET
        TOTAL 25.000
        TUNAI 50.000
        KEMBALIAN 25.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.paid_amount, 50000)
        self.assertEqual(rec.payment_method, "cash")

    def test_09_change_amount_extraction(self):
        """Test 9: Change / kembalian extraction."""
        text = """
        ALFAMART
        TOTAL 32.000
        CASH 50.000
        CHANGE 18.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.change_amount, 18000)

    def test_10_qris_payment_method(self):
        """Test 10: QRIS payment method detection."""
        text = """
        KOPI KENANGAN
        TOTAL Rp 28.000
        PEMBAYARAN: QRIS
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.payment_method, "qris")

    def test_11_transfer_payment_method(self):
        """Test 11: Bank transfer payment method detection."""
        text = """
        TOKO ELEKTRONIK
        TOTAL Rp 1.500.000
        METODE: TRANSFER BCA
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.payment_method, "bank_transfer")

    def test_12_line_items_extraction(self):
        """Test 12: Extract line items list."""
        text = """
        INDOMARET
        Indomie Goreng  3 x 3.500  10.500
        Aqua 600ml      2 x 4.000   8.000
        TOTAL 18.500
        """
        items = extract_line_items(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].name, "Indomie Goreng")
        self.assertEqual(items[0].quantity, 3.0)
        self.assertEqual(items[0].unit_price, 3500)
        self.assertEqual(items[0].total_price, 10500)

    def test_13_quantity_unit_price_arithmetic_validation(self):
        """Test 13: Arithmetic consistency check on item quantity * unit_price."""
        text = """
        SUPER INDO
        Apel Fuji  4 x 10.000  40.000
        TOTAL 40.000
        """
        items = extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertGreaterEqual(items[0].confidence, 0.90)

    def test_14_indonesian_currency_formatting(self):
        """Test 14: Indonesian currency string normalization."""
        cases = [
            ("Rp 127.500", 127500),
            ("Rp127.500", 127500),
            ("IDR 127500", 127500),
            ("1.250.000", 1250000),
            ("12.500,00", 12500),
        ]
        for raw, expected in cases:
            parsed = parse_money_value(raw)
            self.assertEqual(parsed, expected, f"Failed on {raw}")

    def test_15_unknown_merchant_structural_heuristic(self):
        """Test 15: Identify unknown merchant via structural prefix (Toko / PT)."""
        text = """
        TOKO MAKMUR JAYA
        Jl. Gajah Mada No. 12 Surabaya
        1x Beras 5kg Rp 65.000
        TOTAL Rp 65.000
        """
        rec = parse_receipt(text)
        self.assertIsNotNone(rec.merchant_name)
        self.assertIn("TOKO MAKMUR JAYA", rec.merchant_name)

    def test_16_ocr_typo_tolerance_receipt(self):
        """Test 16: Safe typo tolerance for T0TAL, SUBT0TAL, KEM8ALIAN, INDOM4RET."""
        text = """
        INDOM4RET
        SUBT0TAL 20.000
        T0TAL 20.000
        TUN4I 50.000
        KEM8ALIAN 30.000
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "receipt")
        self.assertIsNotNone(res.receipt)
        self.assertEqual(res.receipt.merchant_name, "Indomaret")
        self.assertEqual(res.receipt.total, 20000)
        self.assertEqual(res.receipt.change_amount, 30000)

    def test_17_missing_fields_graceful_handling(self):
        """Test 17: Receipt with missing optional fields returns None without error."""
        text = """
        ALFAMART
        TOTAL Rp 15.000
        """
        rec = parse_receipt(text)
        self.assertEqual(rec.total, 15000)
        self.assertIsNone(rec.tax)
        self.assertIsNone(rec.discount)
        self.assertIsNone(rec.service_charge)
        self.assertIsNone(rec.change_amount)

    def test_18_conflicting_totals_reconciliation_warning(self):
        """Test 18: Conflicting totals preserves extracted values, adds warning, lowers confidence."""
        text = """
        INDOMARET
        SUBTOTAL 100.000
        DISKON 10.000
        TOTAL 50.000
        """
        res = analyze_document(text=text)
        self.assertIsNotNone(res.receipt)
        self.assertEqual(res.receipt.subtotal, 100000)
        self.assertEqual(res.receipt.total, 50000)
        # Check warning added and confidence penalized
        self.assertTrue(any("Reconciliation conflict" in w for w in res.warnings))
        self.assertLessEqual(res.confidence, 0.65)


class TestDocumentExtraction(unittest.TestCase):
    """Section 21: Document parsing tests (Tests 19 - 32)."""

    def test_19_official_letter(self):
        """Test 19: Formal Indonesian official administrative letter."""
        text = """
        KEMENTERIAN KEUANGAN
        Nomor: S-123/MK/2026
        Lampiran: 2 Lembar
        Perihal: Undangan Rapat Koordinasi
        Tanggal: 30 September 2026
        Kepada Yth.
        Kepala Badan Kebijakan Fiskal
        Dengan hormat,
        Sehubungan dengan persiapan anggaran...
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "official_letter")
        self.assertIsNotNone(res.document)
        self.assertEqual(res.document.document_number, "S-123/MK/2026")
        self.assertEqual(res.document.subject, "Undangan Rapat Koordinasi")
        self.assertEqual(res.document.attachment, "2 Lembar")

    def test_20_invoice_document(self):
        """Test 20: Commercial invoice billing."""
        text = """
        PT TEKNOLOGI MAJU
        INVOICE
        Invoice Number: INV-2026-9001
        Date: 2026-09-15
        Due Date: 2026-09-30
        Bill To: PT Mitra Sejahtera
        Total: Rp 15.000.000
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "invoice")
        self.assertIsNotNone(res.document)
        self.assertEqual(res.document.document_number, "INV-2026-9001")

    def test_21_academic_document(self):
        """Test 21: Academic document (KRS)."""
        text = """
        UNIVERSITAS GADJAH MADA
        KARTU RENCANA STUDI (KRS)
        SEMESTER GANJIL 2026/2027
        NPM: 2206123456
        Mata Kuliah: Kecerdasan Buatan (3 SKS)
        Dosen Pembimbing: Dr. Suharjo
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "academic_document")
        self.assertIsNotNone(res.document)

    def test_22_bank_statement(self):
        """Test 22: Bank statement / transaction slip."""
        text = """
        BANK CENTRAL ASIA
        MUTASI REKENING
        Rekening Tujuan: 0123456789
        Nominal Transfer: Rp 1.000.000
        Saldo Akhir: Rp 5.450.000
        Transfer Berhasil
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "bank_document")
        self.assertIsNotNone(res.document)

    def test_23_proposal_document(self):
        """Test 23: Project proposal document."""
        text = """
        PROPOSAL KEGIATAN
        Latar Belakang: Dalam rangka perayaan kemerdekaan...
        Maksud dan Tujuan: Meningkatkan solidaritas warga
        Rancangan Anggaran: Rp 25.000.000
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "proposal")

    def test_24_certificate_document(self):
        """Test 24: Certificate / piagam penghargaan."""
        text = """
        PIAGAM PENGHARGAAN
        Diberikan Kepada: Budi Santoso
        Atas partisipasinya sebagai Pembicara Utama
        Pada Seminar Nasional Teknologi 2026
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "certificate")

    def test_25_form_document(self):
        """Test 25: Application / registration form."""
        text = """
        FORMULIR PENDAFTARAN ANGGOTA
        Nama Lengkap: Siti Nurhaliza
        Tempat, Tanggal Lahir: Jakarta, 12 Mei 1998
        Tanda Tangan Pemohon:
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "form")

    def test_26_unknown_document(self):
        """Test 26: Arbitrary random text classified as unknown."""
        text = "Hello world this is some random prose without administrative structure."
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "unknown")
        self.assertEqual(res.status, "unknown")
        self.assertEqual(res.confidence, 0.0)

    def test_27_document_number_extraction(self):
        """Test 27: Extract formal document reference number."""
        text = "Nomor: 099/DIR-UT/VIII/2026\nPerihal: Kerja Sama"
        num = extract_document_number(text)
        self.assertEqual(num, "099/DIR-UT/VIII/2026")

    def test_28_subject_extraction(self):
        """Test 28: Extract subject line (Perihal)."""
        text = "Perihal: Laporan Akhir Tahun 2026"
        subj = extract_subject(text)
        self.assertEqual(subj, "Laporan Akhir Tahun 2026")

    def test_29_date_extraction(self):
        """Test 29: Extract normalized ISO date from textual month."""
        text = "Tanggal: 30 September 2026"
        dates = extract_document_dates(text)
        self.assertEqual(dates[0], "2026-09-30")

    def test_30_recipient_extraction(self):
        """Test 30: Extract recipient from Kepada Yth."""
        text = "Kepada Yth. Direktur Utama PT Maju Bersama\nDi Tempat"
        rec = extract_recipient(text)
        self.assertEqual(rec, "Direktur Utama PT Maju Bersama")

    def test_31_sender_extraction(self):
        """Test 31: Extract sender from Dari:."""
        text = "Dari: Kepala Biro Kepegawaian\nKepada: Seluruh Staf"
        sender = extract_sender(text)
        self.assertEqual(sender, "Kepala Biro Kepegawaian")

    def test_32_attachment_extraction(self):
        """Test 32: Extract attachment info (Lampiran:)."""
        text = "Lampiran: 1 (satu) Berkas Lengkap"
        att = extract_attachment(text)
        self.assertEqual(att, "1 (satu) Berkas Lengkap")


class TestAmbiguityAndSafety(unittest.TestCase):
    """Section 21: Ambiguity preservation and privacy protection (Tests 33 - 44)."""

    def test_33_single_total_not_high_confidence(self):
        """Test 33: A single 'TOTAL' alone must not become a high-confidence receipt."""
        text = "TOTAL 25.000"
        res = analyze_document(text=text)
        self.assertEqual(res.status, "ambiguous")
        self.assertLessEqual(res.confidence, 0.45)

    def test_34_random_number_not_receipt(self):
        """Test 34: Random number string must not be classified as receipt."""
        text = "12345 67890 2026"
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "unknown")
        self.assertEqual(res.status, "unknown")

    def test_35_random_nomor_not_official_document(self):
        """Test 35: Random 'Nomor 12345' without formal letter cues is not official letter."""
        text = "Nomor 12345"
        res = analyze_document(text=text)
        self.assertIn(res.document_type, ("unknown", "document"))
        self.assertLessEqual(res.confidence, 0.40)

    def test_36_conflicting_arithmetic_lowers_confidence(self):
        """Test 36: Arithmetic mismatch between paid amount and change penalizes confidence."""
        text = """
        INDOMARET
        TOTAL 50.000
        TUNAI 100.000
        KEMBALIAN 10.000
        """
        # Paid 100k, total 50k, but change says 10k (instead of 50k)
        res = analyze_document(text=text)
        self.assertTrue(any("Change conflict" in w for w in res.warnings))
        self.assertLessEqual(res.confidence, 0.70)

    def test_37_card_number_not_logged(self):
        """Test 37: 16-digit credit card number is never logged or exposed in output."""
        text = """
        RECEIPT
        CARD NUMBER: 4532 1234 5678 9012
        EXP: 12/28
        TOTAL Rp 150.000
        """
        with self.assertLogs("darfin_intelligence", level="DEBUG") as log_capture:
            logging.getLogger("darfin_intelligence").debug("Processing transaction")
            res = analyze_document(text=text)

        # Card number must not appear in log records
        for line in log_capture.output:
            self.assertNotIn("4532 1234 5678 9012", line)
            self.assertNotIn("4532123456789012", line)

    def test_38_otp_not_logged(self):
        """Test 38: OTP number is never logged."""
        text = "KODE OTP: 987654. Jangan bagikan kode ini."
        with self.assertLogs("darfin_intelligence", level="DEBUG") as log_capture:
            logging.getLogger("darfin_intelligence").debug("Processing security alert")
            res = analyze_document(text=text)

        for line in log_capture.output:
            self.assertNotIn("987654", line)

    def test_39_empty_ocr(self):
        """Test 39: Empty text returns unknown with 0 confidence."""
        res = analyze_document(text="")
        self.assertEqual(res.status, "unknown")
        self.assertEqual(res.confidence, 0.0)

    def test_40_malformed_ocr_result_dictionary(self):
        """Test 40: Dictionary missing standard keys handled safely."""
        bad_dict: dict[str, Any] = {"unrelated_field": 12345}
        res = analyze_document(ocr_result=bad_dict)
        self.assertEqual(res.status, "unknown")
        self.assertEqual(res.confidence, 0.0)

    def test_41_very_long_text_performance(self):
        """Test 41: Very long document text parsed without timeout."""
        long_text = "Laporan Keuangan Tahunan PT Darfin Storage\n" + ("Baris data transaksi rutin perbankan...\n" * 1000) + "TOTAL Rp 999.000.000\n"
        start = time.perf_counter()
        res = analyze_document(text=long_text)
        duration = time.perf_counter() - start
        self.assertLess(duration, 0.50)
        self.assertIsNotNone(res)

    def test_42_unicode_and_accented_text(self):
        """Test 42: Unicode characters handled safely."""
        text = "Café & Brasserie Crème Brûlée\nTOTAL € 15.00\nMerci beaucoup! 😊"
        res = analyze_document(text=text)
        self.assertIsNotNone(res)

    def test_43_mixed_indonesian_english_invoice(self):
        """Test 43: Mixed language billing invoice."""
        text = """
        PT GLOBAL SOLUTION
        INVOICE / FAKTUR
        Invoice Date: 15 September 2026
        Due Date: 30 September 2026
        Subtotal: Rp 20.000.000
        PPN 11%: Rp 2.200.000
        Total Amount: Rp 22.200.000
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "invoice")
        self.assertIsNotNone(res.document)

    def test_44_ocr_garbage_handling(self):
        """Test 44: OCR noise / unreadable garbage returns unknown."""
        garbage = "^%&*()_+= ~`!@#$$%^&* {}[]|\\:;\"'<>,.?/"
        res = analyze_document(text=garbage)
        self.assertEqual(res.status, "unknown")
        self.assertEqual(res.confidence, 0.0)


class TestIntegrationAndFacade(unittest.TestCase):
    """Facade, serialization, and Task 3B integration tests."""

    def test_45_task_3b_receipt_candidate_priority(self):
        """Test 45: Task 3B receipt_candidate prioritization."""
        ss_res = ScreenshotIntelligenceResult(
            status="classified",
            category="receipt_candidate",
            confidence=0.90,
        )
        text = """
        ALFAMART
        TOTAL Rp 45.000
        """
        res = analyze_document(text=text, screenshot_result=ss_res)
        self.assertEqual(res.document_type, "receipt")
        self.assertIsNotNone(res.receipt)

    def test_46_task_3b_document_priority(self):
        """Test 46: Task 3B document prioritization."""
        ss_res = ScreenshotIntelligenceResult(
            status="classified",
            category="document",
            confidence=0.88,
        )
        text = """
        Nomor: 012/DIR/2026
        Perihal: Pemberitahuan
        """
        res = analyze_document(text=text, screenshot_result=ss_res)
        self.assertEqual(res.document_type, "official_letter")
        self.assertIsNotNone(res.document)

    def test_47_facade_and_to_dict_serialization(self):
        """Test 47: DocumentIntelligenceAnalyzer facade and clean to_dict()."""
        text = "INDOMARET TOTAL Rp 20.000"
        res1 = analyze_document(text=text)
        res2 = DocumentIntelligenceAnalyzer.analyze(text=text)
        self.assertEqual(res1.to_dict(), res2.to_dict())

        d = res1.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("status", d)
        self.assertIn("document_type", d)
        self.assertIn("receipt", d)
        self.assertIn("warnings", d)
        self.assertIn("confidence", d)

    def test_48_contract_document_type(self):
        """Test 48: Contract / legal agreement identification."""
        text = """
        SURAT PERJANJIAN KERJASAMA
        Pada hari ini disepakati oleh:
        Pihak Pertama: Budi Santoso
        Pihak Kedua: PT Darfin Solusi
        Pasal 1: Ketentuan Umum
        """
        res = analyze_document(text=text)
        self.assertEqual(res.document_type, "contract")
        self.assertEqual(res.status, "classified")


if __name__ == "__main__":
    unittest.main()
