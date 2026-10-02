"""Comprehensive test suite for Local OCR Core (Task 3A).

Covers:
- Environment audit and engine detection (Section 1)
- Local OCR engine abstraction and Tesseract runner (Section 2, 21)
- Structured OCRResult model and blocks (Section 3, 16)
- Supported formats (.jpg, .jpeg, .png, .webp) and unsupported rejection (Section 5, 30)
- File size and image dimension boundaries (Section 6, 7)
- Language configuration and support (Section 9)
- Text cleaning and raw preservation (Section 12, 13, 14)
- Confidence scoring (Section 15)
- Error codes and safe exception handling (Section 4, 28)
- Blank image handling (Section 31)
- Corrupt / invalid image handling (Section 29)
- Resource control / timeout handling (Section 24, 36)
- Preprocessing (Section 10)
- Determinism and performance benchmarking (Section 34, 35)
- Real Tesseract integration if available on host (Section 32)
"""

import os
import shutil
import tempfile
import time
import unittest

from PIL import Image, ImageDraw

from darfin_intelligence.ocr.cleaner import clean_ocr_text
from darfin_intelligence.ocr.engine import (
    BaseOCREngine,
    LocalTesseractEngine,
    MockOCREngine,
)
from darfin_intelligence.ocr.models import OCRBlock, OCRResult
from darfin_intelligence.ocr.service import (
    LocalOCREngine,
    OCRService,
    SUPPORTED_FORMATS,
    analyze_image_text,
    extract_text,
    ocr,
    ocr_available,
)


class TestOCRBase(unittest.TestCase):
    """Base setup for creating synthetic test image fixtures using Pillow."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="darfin_ocr_test_")

        # 1. HELLO WORLD fixture
        cls.hello_img_path = os.path.join(cls.test_dir, "fixture_hello.png")
        cls._create_text_image(cls.hello_img_path, "HELLO WORLD")

        # 2. TOTAL Rp 127.500 fixture
        cls.receipt_img_path = os.path.join(cls.test_dir, "fixture_receipt.jpg")
        cls._create_text_image(cls.receipt_img_path, "TOTAL Rp 127.500", fmt="JPEG")

        # 3. RAPAT BESOK 10:00 fixture
        cls.meeting_img_path = os.path.join(cls.test_dir, "fixture_meeting.png")
        cls._create_text_image(cls.meeting_img_path, "RAPAT\nBESOK\n10:00")

        # 4. KRS SEMESTER 5 fixture
        cls.krs_img_path = os.path.join(cls.test_dir, "fixture_krs.webp")
        cls._create_text_image(cls.krs_img_path, "KRS SEMESTER 5", fmt="WEBP")

        # 5. Blank image fixture
        cls.blank_img_path = os.path.join(cls.test_dir, "fixture_blank.png")
        blank = Image.new("RGB", (100, 100), color="white")
        blank.save(cls.blank_img_path, format="PNG")

        # 6. Corrupt invalid image file
        cls.corrupt_img_path = os.path.join(cls.test_dir, "fake_corrupt.jpg")
        with open(cls.corrupt_img_path, "wb") as f:
            f.write(b"NOT_A_REAL_IMAGE_HEADER_DATA_1234567890")

        # Setup standard mock engine for deterministic unit tests
        cls.mock_engine = MockOCREngine(available=True, version="tesseract 5.3.4")
        cls.mock_engine.register_result("hello", "HELLO WORLD", confidence=0.96)
        cls.mock_engine.register_result("receipt", "TOTAL Rp 127.500", confidence=0.92)
        cls.mock_engine.register_result("meeting", "RAPAT\nBESOK\n10:00", confidence=0.88)
        cls.mock_engine.register_result("krs", "KRS SEMESTER 5", confidence=0.94)
        cls.mock_engine.register_result("blank", "", confidence=0.0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    @classmethod
    def _create_text_image(
        cls,
        filepath: str,
        text: str,
        size: tuple[int, int] = (300, 100),
        fmt: str = "PNG",
    ) -> None:
        img = Image.new("RGB", size, color="white")
        draw = ImageDraw.Draw(img)
        lines = text.split("\n")
        y = 10
        for line in lines:
            draw.text((10, y), line, fill="black")
            y += 25
        img.save(filepath, format=fmt)


class TestEnvironmentAndDetection(TestOCRBase):
    """Section 1, 2, 17: Environment audit, availability detection, and versioning."""

    def test_ocr_available_reflects_environment(self):
        """ocr_available() returns a clean boolean without raising exceptions."""
        avail = ocr_available()
        self.assertIsInstance(avail, bool)

    def test_tesseract_engine_availability_check(self):
        """LocalTesseractEngine correctly reports system availability."""
        tess = LocalTesseractEngine()
        has_tesseract = shutil.which("tesseract") is not None
        self.assertEqual(tess.is_available(), has_tesseract)

    def test_tesseract_engine_version_detection(self):
        """get_version() returns a valid string when engine is available, or None."""
        tess = LocalTesseractEngine()
        if tess.is_available():
            ver = tess.get_version()
            self.assertIsNotNone(ver)
            self.assertIsInstance(ver, str)
        else:
            self.assertIsNone(tess.get_version())

    def test_mock_engine_availability_toggle(self):
        """Mock engine allows explicit availability toggling for unit testing."""
        mock = MockOCREngine(available=True)
        self.assertTrue(mock.is_available())
        mock.set_available(False)
        self.assertFalse(mock.is_available())
        self.assertIsNone(mock.get_version())


class TestSupportedFormatsAndValidation(TestOCRBase):
    """Section 5, 6, 7, 28, 29, 30: Input validation, boundaries, and error codes."""

    def setUp(self):
        self.service = LocalOCREngine(engine=self.mock_engine)

    def test_supported_formats_set(self):
        """Section 5: Supported formats must be jpg, jpeg, png, webp."""
        self.assertEqual(SUPPORTED_FORMATS, {"jpg", "jpeg", "png", "webp"})

    def test_unsupported_format_pdf(self):
        """Section 30: PDF file to OCR returns UNSUPPORTED_FORMAT."""
        pdf_path = os.path.join(self.test_dir, "sample.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 sample content")
        res = self.service.process(pdf_path)
        self.assertEqual(res.status, "unsupported_format")
        self.assertEqual(res.error_code, "UNSUPPORTED_FORMAT")

    def test_unsupported_format_mp4(self):
        """Section 30: MP4 file to OCR returns UNSUPPORTED_FORMAT."""
        mp4_path = os.path.join(self.test_dir, "sample.mp4")
        with open(mp4_path, "wb") as f:
            f.write(b"\x00\x00\x00\x20ftypisom")
        res = self.service.process(mp4_path)
        self.assertEqual(res.status, "unsupported_format")
        self.assertEqual(res.error_code, "UNSUPPORTED_FORMAT")

    def test_unsupported_format_txt(self):
        """Section 30: TXT file to OCR returns UNSUPPORTED_FORMAT."""
        txt_path = os.path.join(self.test_dir, "sample.txt")
        with open(txt_path, "w") as f:
            f.write("Just raw text")
        res = self.service.process(txt_path)
        self.assertEqual(res.status, "unsupported_format")
        self.assertEqual(res.error_code, "UNSUPPORTED_FORMAT")

    def test_missing_file_returns_invalid_image(self):
        """Non-existent file path returns INVALID_IMAGE error."""
        res = self.service.process(os.path.join(self.test_dir, "non_existent.jpg"))
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_code, "INVALID_IMAGE")

    def test_corrupt_file_returns_invalid_image(self):
        """Section 29: Corrupt fake image returns INVALID_IMAGE error without crashing."""
        res = self.service.process(self.corrupt_img_path)
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_code, "INVALID_IMAGE")

    def test_file_size_exceeded_returns_ocr_image_too_large(self):
        """Section 6: Image exceeding MAX_OCR_IMAGE_SIZE_MB is rejected."""
        # Service configured with 1 MB limit
        strict_service = LocalOCREngine(engine=self.mock_engine, max_size_mb=1)
        large_path = os.path.join(self.test_dir, "oversized.png")
        # Write 1.5 MB file
        with open(large_path, "wb") as f:
            f.write(b"\x00" * int(1.5 * 1024 * 1024))
        res = strict_service.process(large_path)
        self.assertEqual(res.status, "rejected")
        self.assertEqual(res.error_code, "OCR_IMAGE_TOO_LARGE")

    def test_extreme_dimensions_rejected(self):
        """Section 7: Image exceeding maximum allowed dimensions is rejected."""
        strict_service = LocalOCREngine(engine=self.mock_engine, max_dimension=200)
        # hello_img_path is 300x100 (width 300 > 200)
        res = strict_service.process(self.hello_img_path)
        self.assertEqual(res.status, "rejected")
        self.assertEqual(res.error_code, "OCR_IMAGE_DIMENSIONS_TOO_LARGE")


class TestTextCleaningAndNormalization(unittest.TestCase):
    """Section 12, 13, 14: Text cleaning rules, whitespace normalization, and data preservation."""

    def test_clean_ocr_text_preserves_currency_and_numbers(self):
        """Numbers, currency symbols, and dots must never be stripped or altered."""
        raw = "   TOTAL   Rp   127.500   \n"
        cleaned = clean_ocr_text(raw)
        self.assertEqual(cleaned, "TOTAL Rp 127.500")

    def test_clean_ocr_text_normalizes_crlf_and_spaces(self):
        """CRLF line endings and multiple spaces are standardized."""
        raw = "Line 1   with   spaces\r\nLine 2\t\twith tabs\rLine 3"
        cleaned = clean_ocr_text(raw)
        self.assertEqual(cleaned, "Line 1 with spaces\nLine 2 with tabs\nLine 3")

    def test_clean_ocr_text_collapses_excessive_newlines(self):
        """3 or more consecutive newlines are collapsed into 2 (preserving paragraphs)."""
        raw = "Paragraph 1\n\n\n\n\nParagraph 2"
        cleaned = clean_ocr_text(raw)
        self.assertEqual(cleaned, "Paragraph 1\n\nParagraph 2")

    def test_clean_ocr_text_preserves_multiline_structure(self):
        """Section 32 fixture: 'RAPAT\\nBESOK\\n10:00' preserves exact line breaks."""
        raw = "RAPAT   \n  BESOK  \n10:00  "
        cleaned = clean_ocr_text(raw)
        self.assertEqual(cleaned, "RAPAT\nBESOK\n10:00")

    def test_clean_ocr_text_handles_none_and_empty(self):
        """Empty or None input yields empty string safely."""
        self.assertEqual(clean_ocr_text(None), "")
        self.assertEqual(clean_ocr_text(""), "")
        self.assertEqual(clean_ocr_text("   \n\t  "), "")


class TestOCRProcessingWithFixtures(TestOCRBase):
    """Section 3, 13, 15, 16, 27, 31, 32: Fixture extractions and result model."""

    def setUp(self):
        self.service = LocalOCREngine(engine=self.mock_engine)

    def test_ocr_fixture_hello_world(self):
        """Fixture 1: 'HELLO WORLD' extraction and structured result."""
        res = self.service.process(self.hello_img_path)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "HELLO WORLD")
        self.assertEqual(res.confidence, 0.96)
        self.assertEqual(res.engine, "mock")
        self.assertGreater(len(res.blocks), 0)

    def test_ocr_fixture_receipt_total(self):
        """Fixture 2: 'TOTAL Rp 127.500' extraction."""
        res = self.service.process(self.receipt_img_path)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "TOTAL Rp 127.500")
        self.assertEqual(res.confidence, 0.92)

    def test_ocr_fixture_meeting_notice(self):
        """Fixture 3: 'RAPAT\\nBESOK\\n10:00' multi-line notice."""
        res = self.service.process(self.meeting_img_path)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "RAPAT\nBESOK\n10:00")

    def test_ocr_fixture_krs(self):
        """Fixture 4: 'KRS SEMESTER 5' WebP extraction."""
        res = self.service.process(self.krs_img_path)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "KRS SEMESTER 5")
        self.assertEqual(res.confidence, 0.94)

    def test_ocr_blank_image_returns_success_empty_text(self):
        """Section 31: Blank image returns success with empty text, not an error."""
        res = self.service.process(self.blank_img_path)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "")
        self.assertIsNone(res.error_code)

    def test_ocr_raw_text_preserved_distinct_from_normalized(self):
        """Section 13: raw_text preserves exact original string while normalized_text cleans it."""
        mock = MockOCREngine()
        mock.register_result("test", "   RAW   UNTRIMMED   \r\nTEXT   ")
        service = LocalOCREngine(engine=mock)
        res = service.process(self.hello_img_path)
        self.assertEqual(res.raw_text, "   RAW   UNTRIMMED   \r\nTEXT   ")
        self.assertEqual(res.normalized_text, "RAW UNTRIMMED\nTEXT")

    def test_ocr_result_to_dict(self):
        """OCRResult serializes safely to dictionary without exposing exceptions."""
        res = self.service.process(self.hello_img_path)
        d = res.to_dict()
        self.assertIn("status", d)
        self.assertIn("text", d)
        self.assertIn("raw_text", d)
        self.assertIn("confidence", d)
        self.assertIn("engine", d)
        self.assertIn("processing_time_ms", d)

    def test_ocr_sha256_hash_generated(self):
        """Section 27: Local file SHA-256 hash is computed for identification."""
        res = self.service.process(self.hello_img_path)
        self.assertIsNotNone(res.image_hash)
        self.assertEqual(len(res.image_hash), 64)


class TestResourceControlAndErrors(TestOCRBase):
    """Section 4, 10, 24, 28: Timeout, engine error, unavailability, and preprocessing."""

    def test_ocr_timeout_handling(self):
        """Section 24: Subprocess timeout produces status='timeout' and error_code='OCR_TIMEOUT'."""
        mock = MockOCREngine()
        mock.set_simulate_timeout(True)
        service = LocalOCREngine(engine=mock, timeout_seconds=1)
        res = service.process(self.hello_img_path)
        self.assertEqual(res.status, "timeout")
        self.assertEqual(res.error_code, "OCR_TIMEOUT")
        self.assertIn("timed out", res.error_message.lower())

    def test_ocr_engine_error_handling(self):
        """Section 28: Engine internal failure returns OCR_ENGINE_ERROR safely without leaking traceback."""
        mock = MockOCREngine()
        mock.set_simulate_error("Unexpected native core dump")
        service = LocalOCREngine(engine=mock)
        res = service.process(self.hello_img_path)
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_code, "OCR_ENGINE_ERROR")
        self.assertNotIn("core dump", res.error_message)

    def test_ocr_unavailable_error_handling(self):
        """Section 1: Unavailable engine returns OCR_UNAVAILABLE."""
        mock = MockOCREngine(available=False)
        service = LocalOCREngine(engine=mock)
        res = service.process(self.hello_img_path)
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_code, "OCR_UNAVAILABLE")

    def test_ocr_preprocessing_option(self):
        """Section 10: preprocess=True executes grayscale and contrast enhancement safely."""
        service = LocalOCREngine(engine=self.mock_engine)
        res = service.process(self.hello_img_path, preprocess=True)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "HELLO WORLD")

    def test_analyze_image_text_hook_safe_wrapper(self):
        """Section 39: analyze_image_text wrapper never crashes."""
        res = analyze_image_text("non_existent_file.png")
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_code, "INVALID_IMAGE")


class TestDeterminismAndPerformance(TestOCRBase):
    """Section 34, 35: Determinism verification and performance benchmarking."""

    def test_ocr_result_determinism(self):
        """Section 34: Running OCR twice on identical input produces identical normalized output."""
        service = LocalOCREngine(engine=self.mock_engine)
        res1 = service.process(self.receipt_img_path)
        res2 = service.process(self.receipt_img_path)
        self.assertEqual(res1.text, res2.text)
        self.assertEqual(res1.confidence, res2.confidence)
        self.assertEqual(res1.image_hash, res2.image_hash)

    def test_ocr_performance_benchmark(self):
        """Section 35: In-memory OCR calls must be lightweight and fast."""
        service = LocalOCREngine(engine=self.mock_engine)
        count = 20
        start = time.perf_counter()
        for _ in range(count):
            res = service.process(self.hello_img_path)
            self.assertEqual(res.status, "success")
        total_time = time.perf_counter() - start
        avg_ms = (total_time / count) * 1000
        # In-memory execution should easily be under 20ms per image
        self.assertLess(avg_ms, 25.0, f"Average OCR time too high: {avg_ms:.2f}ms")

    def test_facade_service_api(self):
        """Section 2: OCRService facade methods operate identically to standalone functions."""
        res = OCRService.ocr(self.hello_img_path, engine=self.mock_engine)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.text, "HELLO WORLD")

        res_ext = OCRService.extract_text(self.receipt_img_path, engine=self.mock_engine)
        self.assertEqual(res_ext.status, "success")
        self.assertEqual(res_ext.text, "TOTAL Rp 127.500")


class TestRealTesseractIntegration(TestOCRBase):
    """Section 32: Real Tesseract integration test (runs conditionally if tesseract is installed)."""

    def test_real_tesseract_if_installed(self):
        """Runs real Tesseract OCR on test fixtures if Tesseract CLI is installed in environment."""
        engine = LocalTesseractEngine()
        if not engine.is_available():
            raise unittest.SkipTest("Tesseract CLI is not installed on this host. Skipping integration test.")

        service = LocalOCREngine(engine=engine)
        res = service.process(self.hello_img_path, language="eng")
        self.assertEqual(res.status, "success")
        self.assertIn("HELLO", res.text.upper())


if __name__ == "__main__":
    unittest.main()
