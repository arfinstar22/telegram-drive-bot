"""Unit and integration tests for Task 3B Screenshot Intelligence Core.

100% deterministic, local execution using standard library unittest.
Zero AI APIs, zero external dependencies.

Tests cover:
- Core category classification (reminder, receipt_candidate, shopping, education, conversation, etc.)
- Structured entity extraction (dates, times, prices, URLs, emails, phone numbers, merchant, codes)
- Ambiguity detection and dampening
- Multi-signal requirement vs false positives
- OCR error resilience
- OCR confidence-aware dampening
- Privacy preservation (OTP masking, zero sensitive logging, credit card detection)
- Determinism and high-volume performance (10,000 strings)
"""

from __future__ import annotations

import logging
import time
import unittest
from typing import Any

from darfin_intelligence.ocr.models import OCRResult
from darfin_intelligence.screenshot import (
    ScreenshotAnalyzer,
    ScreenshotIntelligenceResult,
    analyze_screenshot,
    extract_all_entities,
    extract_codes_and_sensitive,
    extract_dates,
    extract_emails,
    extract_merchant,
    extract_phone_numbers,
    extract_prices,
    extract_times,
    extract_urls,
)


class TestRequiredPromptTests(unittest.TestCase):
    """Section 37 Required Core Tests."""

    def test_01_required_test_1_reminder(self):
        """TEST 1: 'Rapat besok pukul 10:00' -> reminder with relative_date=tomorrow & time=10:00."""
        text = "Rapat besok pukul 10:00"
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "reminder")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.85)

        rel_dates = [d for d in res.entities.dates if d.type == "relative"]
        self.assertGreaterEqual(len(rel_dates), 1)
        self.assertEqual(rel_dates[0].value, "tomorrow")
        self.assertIn("10:00", res.entities.times)

    def test_02_required_test_2_receipt_candidate(self):
        """TEST 2: 'INDOMARET TOTAL Rp127.500' -> receipt_candidate with price=127500 & merchant=Indomaret."""
        text = "INDOMARET\nTOTAL Rp127.500"
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "receipt_candidate")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.85)

        self.assertEqual(res.entities.merchant, "Indomaret")
        self.assertGreaterEqual(len(res.entities.prices), 1)
        self.assertEqual(res.entities.prices[0].amount, 127500)
        self.assertEqual(res.entities.prices[0].currency, "IDR")

    def test_03_required_test_3_shopping(self):
        """TEST 3: 'Promo 50% checkout sekarang' -> shopping."""
        text = "Promo 50% checkout sekarang"
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "shopping")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.45)

    def test_04_required_test_4_education(self):
        """TEST 4: 'KRS SEMESTER 5 Pemrograman Web' -> education."""
        text = "KRS SEMESTER 5\nPemrograman Web"
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "education")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.55)

    def test_05_required_test_5_conversation(self):
        """TEST 5: Multi-speaker chat dialogue -> conversation."""
        text = "Budi:\nBesok jadi?\nAni:\nIya jam 8."
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "conversation")
        self.assertEqual(res.status, "classified")
        self.assertIn("Budi", res.entities.names)
        self.assertIn("Ani", res.entities.names)

    def test_06_required_test_6_github_webpage_or_code(self):
        """TEST 6: 'https://github.com/example/project' -> webpage or code."""
        text = "https://github.com/example/project"
        res = analyze_screenshot(text)

        self.assertIn(res.category, ("webpage", "code"))
        self.assertIn("https://github.com/example/project", res.entities.urls)

    def test_07_required_test_7_otp_notification_and_privacy(self):
        """TEST 7: 'OTP 123456' -> notification & OTP must NEVER appear unmasked in logs or text."""
        text = "Kode OTP Anda adalah 123456. Jangan berikan kepada siapapun."

        with self.assertLogs("darfin_intelligence", level="DEBUG") as log_capture:
            # Emit a dummy log to ensure capture has records
            logging.getLogger("darfin_intelligence").debug("Analyzing input text")
            res = analyze_screenshot(text)

        self.assertEqual(res.category, "notification")
        self.assertEqual(res.status, "classified")

        # Verify code is masked in entities
        self.assertGreaterEqual(len(res.entities.codes), 1)
        self.assertNotIn("123456", res.entities.codes[0])
        self.assertIn("***456", res.entities.codes[0])

        # Verify explanation and evidence do NOT leak the raw OTP
        for exp in res.explanation:
            self.assertNotIn("123456", exp)
        for ev in res.evidence:
            self.assertNotIn("123456", ev)

        # Verify log records do not contain raw OTP
        for output_line in log_capture.output:
            self.assertNotIn("123456", output_line)


class TestEdgeCasesAndSignals(unittest.TestCase):
    """Sections 38-47: False positives, errors, ambiguity, and performance."""

    def test_08_false_positive_test_no_time_reminder(self):
        """TEST 38: 'Perusahaan akan rapat besok' without time expression must not be high-confidence reminder."""
        text = "Perusahaan akan rapat besok"
        res = analyze_screenshot(text)

        self.assertLessEqual(res.confidence, 0.60)
        self.assertEqual(len(res.entities.times), 0)

    def test_09_ocr_error_tolerance(self):
        """TEST 39: 'Rapat be5ok puku1 10:00' -> parses rapat and 10:00 safely without hallucination."""
        text = "Rapat be5ok puku1 10:00"
        res = analyze_screenshot(text)

        self.assertEqual(res.category, "reminder")
        self.assertIn("10:00", res.entities.times)
        self.assertIsNone(res.entities.merchant)
        self.assertEqual(len(res.entities.urls), 0)

    def test_10_price_normalization_variants(self):
        """TEST 40: Normalizes Rp 127.500, Rp127.500, Rp 1.250.000, IDR 127500 safely."""
        cases = [
            ("Rp 127.500", 127500, "IDR"),
            ("Rp127.500", 127500, "IDR"),
            ("Rp 1.250.000", 1250000, "IDR"),
            ("IDR 127500", 127500, "IDR"),
        ]
        for text, expected_amount, expected_curr in cases:
            prices = extract_prices(text)
            self.assertGreaterEqual(len(prices), 1, f"Failed on {text}")
            self.assertEqual(prices[0].amount, expected_amount)
            self.assertEqual(prices[0].currency, expected_curr)

    def test_11_date_normalization_variants(self):
        """TEST 41: Extracts 30/09/2026, 30-09-2026, 2026-09-30, 30 Sep 2026, besok, lusa."""
        cases = [
            ("30/09/2026", "absolute", "2026-09-30"),
            ("30-09-2026", "absolute", "2026-09-30"),
            ("2026-09-30", "absolute", "2026-09-30"),
            ("30 Sep 2026", "absolute", "2026-09-30"),
            ("besok", "relative", "tomorrow"),
            ("lusa", "relative", "day_after_tomorrow"),
        ]
        for text, exp_type, exp_val in cases:
            dates = extract_dates(text)
            self.assertGreaterEqual(len(dates), 1, f"Failed on {text}")
            self.assertEqual(dates[0].type, exp_type)
            self.assertEqual(dates[0].value, exp_val)

    def test_12_url_extraction_no_crawl(self):
        """TEST 42: Extracts multiple URLs without fetching."""
        text = "Visit https://darfin.app/docs or http://api.darfin.local and www.example.org/test"
        urls = extract_urls(text)

        self.assertIn("https://darfin.app/docs", urls)
        self.assertIn("http://api.darfin.local", urls)
        self.assertIn("www.example.org/test", urls)

    def test_13_email_extraction(self):
        """TEST 43: Extracts hello@example.com correctly."""
        text = "Send queries to hello@example.com or support@darfin.id please."
        emails = extract_emails(text)

        self.assertIn("hello@example.com", emails)
        self.assertIn("support@darfin.id", emails)

    def test_14_phone_number_extraction(self):
        """TEST 44: Extracts 081234567890 and +6281234567890."""
        cases = [
            ("Contact: 081234567890", "081234567890"),
            ("Call +6281234567890 now", "+6281234567890"),
            ("WA: 0812-3456-7890", "081234567890"),
        ]
        for text, exp_clean in cases:
            phones = extract_phone_numbers(text)
            self.assertGreaterEqual(len(phones), 1, f"Failed on {text}")
            self.assertEqual(phones[0], exp_clean)

    def test_15_ambiguity_test_promo_besok(self):
        """TEST 45: 'Promo besok' -> ambiguous or low-confidence, NEVER high-confidence reminder."""
        text = "Promo besok"
        res = analyze_screenshot(text)

        self.assertEqual(res.status, "ambiguous")
        self.assertLessEqual(res.confidence, 0.50)
        self.assertIn("Ambiguous category", res.explanation[0])

    def test_16_ocr_confidence_dampening(self):
        """TEST 46: Same text with high vs low OCR confidence."""
        ocr_high = OCRResult(status="success", raw_text="Rapat besok pukul 10:00", confidence=0.95)
        ocr_low = OCRResult(status="success", raw_text="Rapat besok pukul 10:00", confidence=0.40)

        res_high = analyze_screenshot(ocr_high)
        res_low = analyze_screenshot(ocr_low)

        self.assertEqual(res_high.category, "reminder")
        self.assertEqual(res_low.category, "reminder")
        self.assertGreater(res_high.confidence, res_low.confidence)
        self.assertLessEqual(res_low.confidence, 0.55)

    def test_17_determinism_100_runs(self):
        """TEST 47: 100 identical runs on same OCRResult produce identical output."""
        ocr_input = OCRResult(status="success", raw_text="INDOMARET\nTOTAL Rp127.500", confidence=0.92)
        baseline = analyze_screenshot(ocr_input).to_dict()

        for i in range(100):
            res = analyze_screenshot(ocr_input).to_dict()
            self.assertEqual(res, baseline, f"Non-deterministic mismatch at {i}")

    def test_18_performance_10000_iterations(self):
        """TEST 48: High-performance benchmark on 10,000 strings without external calls."""
        samples = [
            "Rapat besok pukul 10:00",
            "INDOMARET TOTAL Rp127.500",
            "Promo 50% checkout sekarang",
            "KRS SEMESTER 5 Pemrograman Web",
            "Budi:\nBesok jadi?\nAni:\nIya jam 8.",
            "https://github.com/example/project",
            "OTP 123456",
            "Perusahaan akan rapat besok",
            "Rapat be5ok puku1 10:00",
            "Card number: 4532 1234 5678 9012 Exp: 12/28",
        ]

        start = time.perf_counter()
        for i in range(10000):
            analyze_screenshot(samples[i % len(samples)])
        duration = time.perf_counter() - start

        # Benchmark: under 3.0 seconds for 10,000 items (> 3,300 items/sec)
        self.assertLess(duration, 3.0, f"Benchmark took {duration:.2f}s")


class TestCategoriesAndPrivacy(unittest.TestCase):
    """Additional category verification, edge cases, and privacy safety."""

    def test_19_privacy_credit_card_detection(self):
        """Credit card number (16 digits) flagged as payment_sensitive=True, zero logging."""
        text = "Payment card: 4532 1234 5678 9012 Exp: 12/28"
        res = analyze_screenshot(text)

        self.assertTrue(res.entities.payment_sensitive)
        self.assertNotIn("4532", " ".join(res.entities.codes))

    def test_20_code_category_python(self):
        """Detects Python code snippet as 'code'."""
        text = """
        import os
        from datetime import datetime

        def process_data(records):
            class DataHandler:
                pass
            return True
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "code")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.70)

    def test_21_code_category_stack_trace(self):
        """Detects traceback error as 'code'."""
        text = """
        Traceback (most recent call last):
          File "main.py", line 42, in <module>
            process_items()
        TypeError: unsupported operand type(s)
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "code")
        self.assertEqual(res.status, "classified")

    def test_22_document_category_official_letter(self):
        """Detects formal Indonesian administrative letter as 'document'."""
        text = """
        Nomor: 045/SK/DIR/IX/2026
        Lampiran: 1 Berkas
        Perihal: Surat Keputusan Pengangkatan
        Kepada Yth. Sdr. Budi Santoso
        Dengan hormat,
        Menimbang bahwa perlu adanya pengangkatan...
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "document")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.75)

    def test_23_social_media_category_instagram(self):
        """Detects social media metrics as 'social_media'."""
        text = """
        Instagram @darfinstar
        12.5k followers • 450 following
        150 postingan
        1.2k likes • 84 comments
        Bagikan postingan ini
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "social_media")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.70)

    def test_24_contact_card_category(self):
        """Detects business contact card with phone + email as 'contact'."""
        text = """
        Darfinstar Studio
        Email: contact@darfinstar.com
        Telp: +6281234567890
        Jakarta, Indonesia
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "contact")
        self.assertEqual(res.status, "classified")
        self.assertIn("contact@darfinstar.com", res.entities.emails)
        self.assertIn("+6281234567890", res.entities.phone_numbers)

    def test_25_finance_candidate_bank_transfer(self):
        """Detects bank transfer statement as 'finance_candidate'."""
        text = """
        m-BCA
        Transfer Berhasil
        Rekening Tujuan: 1234567890
        Nominal Transfer: Rp 500.000
        Saldo Rekening: Rp 2.500.000
        """
        res = analyze_screenshot(text)
        self.assertIn(res.category, ("finance_candidate", "receipt_candidate"))
        self.assertEqual(res.status, "classified")

    def test_26_empty_or_whitespace_input(self):
        """Empty or whitespace input returns status='unknown', category='screenshot_unknown'."""
        res_empty = analyze_screenshot("")
        self.assertEqual(res_empty.status, "unknown")
        self.assertEqual(res_empty.category, "screenshot_unknown")
        self.assertEqual(res_empty.confidence, 0.0)

        res_spaces = analyze_screenshot("   \n\t   ")
        self.assertEqual(res_spaces.status, "unknown")
        self.assertEqual(res_spaces.category, "screenshot_unknown")

    def test_27_dict_input_support(self):
        """Accepts dictionary representation of OCRResult."""
        data = {
            "raw_text": "INDOMARET TOTAL Rp50.000",
            "confidence": 0.88,
        }
        res = analyze_screenshot(data)
        self.assertEqual(res.category, "receipt_candidate")
        self.assertEqual(res.ocr_confidence, 0.88)

    def test_28_screenshot_analyzer_class(self):
        """ScreenshotAnalyzer class facade provides identical results."""
        text = "Rapat besok pukul 10:00"
        res1 = analyze_screenshot(text)
        res2 = ScreenshotAnalyzer.analyze(text)
        self.assertEqual(res1.to_dict(), res2.to_dict())

    def test_29_relative_dates_yesterday_and_today(self):
        """Extracts 'hari ini', 'kemarin', 'lusa'."""
        text = "Kemarin kami mulai, hari ini kami lanjutkan, dan lusa kami selesaikan."
        dates = extract_dates(text)
        vals = [d.value for d in dates]
        self.assertIn("yesterday", vals)
        self.assertIn("today", vals)
        self.assertIn("day_after_tomorrow", vals)

    def test_30_time_extraction_12h_ampm(self):
        """Normalizes 10 AM, 10:30 PM, 12 PM, 12 AM."""
        cases = [
            ("Meeting at 10 AM", "10:00"),
            ("Dinner at 10:30 PM", "22:30"),
            ("Noon at 12 PM", "12:00"),
            ("Midnight at 12 AM", "00:00"),
        ]
        for text, exp in cases:
            times = extract_times(text)
            self.assertIn(exp, times, f"Failed on {text}")

    def test_31_time_extraction_dot_notation(self):
        """Normalizes 10.00 and 22.45."""
        text = "Jadwal: 10.00 WIB sampai 22.45 WIB"
        times = extract_times(text)
        self.assertIn("10:00", times)
        self.assertIn("22:45", times)

    def test_32_indonesian_textual_dates(self):
        """Extracts Indonesian textual dates like '15 Agustus 2026'."""
        text = "Pelaksanaan ujian pada 15 Agustus 2026 dan pengumuman 10 September 2026."
        dates = extract_dates(text)
        vals = [d.value for d in dates]
        self.assertIn("2026-08-15", vals)
        self.assertIn("2026-09-10", vals)

    def test_33_known_merchant_extraction(self):
        """Extracts known merchant brand names."""
        cases = [
            ("Belanja di ALFAMART tadi pagi", "Alfamart"),
            ("Ngopi di Starbucks Grand Indonesia", "Starbucks"),
            ("Beli ayam di KFC", "Kfc"),
        ]
        for text, exp_brand in cases:
            m = extract_merchant(text)
            self.assertEqual(m, exp_brand)

    def test_34_clean_url_strips_trailing_punctuation(self):
        """Strips trailing punctuation like dot or comma from URLs."""
        text = "Check out https://darfin.org/report, and https://darfin.org/api."
        urls = extract_urls(text)
        self.assertIn("https://darfin.org/report", urls)
        self.assertIn("https://darfin.org/api", urls)

    def test_35_to_dict_serialization(self):
        """Result object serializes cleanly to JSON-compatible dict."""
        text = "INDOMARET TOTAL Rp127.500"
        res = analyze_screenshot(text)
        d = res.to_dict()

        self.assertIsInstance(d, dict)
        self.assertEqual(d["status"], "classified")
        self.assertEqual(d["category"], "receipt_candidate")
        self.assertIsInstance(d["confidence"], float)
        self.assertIsInstance(d["entities"], dict)
        self.assertIsInstance(d["signals"], list)
        self.assertIsInstance(d["explanation"], list)

    def test_36_unrecognized_text_returns_unknown(self):
        """Random unclassified text returns status='unknown', category='screenshot_unknown'."""
        text = "xyz qwe asd lorem ipsum dolor sit"
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "screenshot_unknown")
        self.assertEqual(res.status, "unknown")
        self.assertEqual(res.confidence, 0.0)

    def test_37_receipt_beats_shopping_when_total_and_merchant_present(self):
        """Receipt candidate wins over shopping when cashier, total and merchant co-occur."""
        text = """
        ALFAMART
        Jl. Merdeka No. 10
        Kasir: Siti
        1x Susu Rp 18.000
        1x Roti Rp 12.000
        SUBTOTAL Rp 30.000
        TOTAL Rp 30.000
        TUNAI Rp 50.000
        KEMBALIAN Rp 20.000
        """
        res = analyze_screenshot(text)
        self.assertEqual(res.category, "receipt_candidate")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.85)
        self.assertEqual(res.entities.merchant, "Alfamart")

    def test_38_explanation_formatting_and_substance(self):
        """Explanation provides clear reasons with signal indicators."""
        text = "Rapat besok pukul 10:00"
        res = analyze_screenshot(text)

        self.assertGreaterEqual(len(res.explanation), 2)
        self.assertIn("Category identified as 'reminder'", res.explanation[0])
        self.assertTrue(any("✓" in line for line in res.explanation[1:]))


if __name__ == "__main__":
    unittest.main()
