"""Test suite for darfin_intelligence engine.

40+ meaningful tests covering:
- File type detection (MIME, extension, Telegram type)
- MIME normalization
- Extension normalization
- Filename tokenizer
- Alias/technical marker normalization
- Media parser (title, year, resolution, source, codec, audio)
- Year detection
- Resolution detection
- Source detection
- Codec detection
- Audio codec detection
- Series pattern detection (S01E01)
- Generic document classification
- Strong vs weak signal hierarchy
- Negative evidence (domain keywords never override file-type evidence)
- Confidence scoring
- Ambiguous result handling
- Explain mode
- WhatsApp filename parsing
- Screenshot filename parsing
- Failure resilience
- Original filename preservation
"""

import unittest
from darfin_intelligence import analyze, IntelligenceResult
from darfin_intelligence.tokenizer import tokenize, get_extension
from darfin_intelligence.normalizer import (
    normalize_resolution, normalize_source, normalize_codec,
    normalize_audio_codec, is_technical_marker, is_year,
)
from darfin_intelligence.dictionaries import mime_to_family, EXTENSION_FAMILIES
from darfin_intelligence.signals import collect_signals, score_signals, compute_confidence
from darfin_intelligence.parsers import parse_media_filename, parse_whatsapp_filename


class TestTokenizer(unittest.TestCase):
    """Filename tokenizer tests."""

    def test_dot_separated(self):
        tokens = tokenize("Movie.2026.1080p.WEB-DL.mkv")
        self.assertIn("Movie", tokens)
        self.assertIn("2026", tokens)
        self.assertIn("1080p", tokens)
        self.assertIn("WEB-DL", tokens)

    def test_underscore_separated(self):
        tokens = tokenize("video_20260929_015229.mp4")
        self.assertIn("video", tokens)

    def test_mixed_delimiters(self):
        tokens = tokenize("Kualitas.Tinggi-Film_2026[WEB-DL].mkv")
        self.assertIn("Kualitas", tokens)
        self.assertIn("Tinggi", tokens)
        self.assertIn("Film", tokens)
        self.assertIn("2026", tokens)
        self.assertIn("WEB-DL", tokens)

    def test_compound_webdl_preserved(self):
        tokens = tokenize("Movie.2026.WEB.DL.mkv")
        self.assertIn("WEB-DL", tokens)

    def test_compound_bluray_preserved(self):
        tokens = tokenize("Film.2026.Blu.Ray.mkv")
        self.assertIn("BluRay", tokens)

    def test_compound_h264_preserved(self):
        tokens = tokenize("Movie.H.264.mkv")
        self.assertIn("H.264", tokens)

    def test_extension_stripped(self):
        tokens = tokenize("document.pdf")
        self.assertNotIn("pdf", tokens)
        self.assertIn("document", tokens)

    def test_get_extension(self):
        self.assertEqual(get_extension("file.mp4"), "mp4")
        self.assertEqual(get_extension("file.PDF"), "pdf")
        self.assertIsNone(get_extension("noextension"))
        self.assertEqual(get_extension("archive.tar.gz"), "gz")


class TestNormalizer(unittest.TestCase):
    """Token normalization tests."""

    def test_resolution_normalize(self):
        self.assertEqual(normalize_resolution("1080p"), "1080p")
        self.assertEqual(normalize_resolution("4k"), "2160p")
        self.assertEqual(normalize_resolution("UHD"), "2160p")
        self.assertEqual(normalize_resolution("FHD"), "1080p")
        self.assertEqual(normalize_resolution("HD"), "720p")

    def test_source_normalize(self):
        self.assertEqual(normalize_source("web-dl"), "WEB-DL")
        self.assertEqual(normalize_source("WEBDL"), "WEB-DL")
        self.assertEqual(normalize_source("webrip"), "WEBRip")
        self.assertEqual(normalize_source("BluRay"), "BluRay")
        self.assertEqual(normalize_source("dvdrip"), "DVDRip")

    def test_codec_normalize(self):
        self.assertEqual(normalize_codec("x264"), "x264")
        self.assertEqual(normalize_codec("H264"), "H.264")
        self.assertEqual(normalize_codec("hevc"), "HEVC")
        self.assertEqual(normalize_codec("x265"), "x265")

    def test_audio_codec_normalize(self):
        self.assertEqual(normalize_audio_codec("aac"), "AAC")
        self.assertEqual(normalize_audio_codec("DTS"), "DTS")
        self.assertEqual(normalize_audio_codec("truehd"), "TrueHD")
        self.assertEqual(normalize_audio_codec("eac3"), "EAC3")

    def test_is_technical_marker(self):
        self.assertTrue(is_technical_marker("1080p"))
        self.assertTrue(is_technical_marker("WEB-DL"))
        self.assertTrue(is_technical_marker("x264"))
        self.assertFalse(is_technical_marker("Movie"))
        self.assertFalse(is_technical_marker("Perusahaan"))

    def test_is_year(self):
        self.assertTrue(is_year("2026"))
        self.assertTrue(is_year("1999"))
        self.assertFalse(is_year("1080"))
        self.assertFalse(is_year("123"))
        self.assertFalse(is_year("20261"))


class TestDictionaries(unittest.TestCase):
    """Dictionary and MIME mapping tests."""

    def test_extension_families(self):
        self.assertEqual(EXTENSION_FAMILIES["mp4"], "video")
        self.assertEqual(EXTENSION_FAMILIES["jpg"], "image")
        self.assertEqual(EXTENSION_FAMILIES["mp3"], "audio")
        self.assertEqual(EXTENSION_FAMILIES["pdf"], "document")
        self.assertEqual(EXTENSION_FAMILIES["zip"], "archive")
        self.assertEqual(EXTENSION_FAMILIES["apk"], "application")

    def test_mime_to_family(self):
        self.assertEqual(mime_to_family("video/mp4"), "video")
        self.assertEqual(mime_to_family("video/x-matroska"), "video")
        self.assertEqual(mime_to_family("image/jpeg"), "image")
        self.assertEqual(mime_to_family("audio/mpeg"), "audio")
        self.assertEqual(mime_to_family("application/pdf"), "document")
        self.assertEqual(mime_to_family("application/zip"), "archive")
        self.assertIsNone(mime_to_family(None))
        self.assertIsNone(mime_to_family(""))

    def test_mime_unknown(self):
        result = mime_to_family("application/octet-stream")
        self.assertIn(result, ("other", None))


class TestSignalEngine(unittest.TestCase):
    """Signal collection and scoring tests."""

    def test_mime_signal_collected(self):
        signals = collect_signals([], "mp4", "video/mp4")
        mime_sigs = [s for s in signals if s.source == "mime"]
        self.assertTrue(len(mime_sigs) > 0)
        self.assertEqual(mime_sigs[0].weight, 80)

    def test_extension_signal_collected(self):
        signals = collect_signals([], "pdf", None)
        ext_sigs = [s for s in signals if s.source == "extension"]
        self.assertTrue(len(ext_sigs) > 0)
        self.assertEqual(ext_sigs[0].category, "document")

    def test_technical_marker_signal(self):
        signals = collect_signals(["1080p", "WEB-DL"], None, None)
        tech_sigs = [s for s in signals if s.source == "technical_marker"]
        self.assertTrue(len(tech_sigs) >= 2)

    def test_domain_keyword_signal(self):
        signals = collect_signals(["perusahaan"], None, None)
        domain_sigs = [s for s in signals if s.source == "domain_keyword"]
        self.assertTrue(len(domain_sigs) > 0)
        self.assertEqual(domain_sigs[0].weight, 3)

    def test_score_aggregation(self):
        signals = collect_signals(["1080p"], "mp4", "video/mp4")
        scores = score_signals(signals)
        self.assertIn("video", scores)
        self.assertGreater(scores["video"], 0)

    def test_confidence_sums_to_one(self):
        signals = collect_signals(["1080p"], "mp4", "video/mp4")
        scores = score_signals(signals)
        confidence = compute_confidence(scores)
        families = [v for k, v in confidence.items() if k in ("video", "image", "audio", "document", "archive")]
        if families:
            self.assertAlmostEqual(sum(families), 1.0, places=2)


class TestStrongVsWeakSignals(unittest.TestCase):
    """Critical: domain keywords must never override file-type evidence."""

    def test_perusahaan_corporat_pdf_mp4_is_video(self):
        """THE critical test from the prompt."""
        result = analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.year, 2026)
        self.assertIn("Perusahaan", result.entities.title)
        self.assertIn("PDF", result.entities.title)

    def test_laporan_1080p_webdl_mp4_is_video(self):
        result = analyze("Laporan.2026.1080p.WEB-DL.x264.mp4", mime_type="video/mp4")
        self.assertEqual(result.file_type.family, "video")

    def test_office_keyword_weak_against_video(self):
        result = analyze("Rapat.Kantor.2026.720p.WEBRip.mkv")
        self.assertEqual(result.file_type.family, "video")

    def test_education_keyword_weak_against_video(self):
        result = analyze("Kuliah.Semester.3.2026.1080p.BluRay.x265.mkv")
        self.assertEqual(result.file_type.family, "video")

    def test_finance_keyword_weak_against_video(self):
        result = analyze("Invoice.Payment.2026.720p.HDTV.mp4")
        self.assertEqual(result.file_type.family, "video")

    def test_pure_document_stays_document(self):
        result = analyze("Laporan_Keuangan_2026.pdf", mime_type="application/pdf")
        self.assertEqual(result.file_type.family, "document")

    def test_pure_image_stays_image(self):
        result = analyze("foto_liburan_bali.jpg", mime_type="image/jpeg")
        self.assertEqual(result.file_type.family, "image")

    def test_mime_overrides_misleading_extension_tokens(self):
        """MIME is stronger than extension name tokens."""
        result = analyze("report.pdf.mp4", mime_type="video/mp4")
        self.assertEqual(result.file_type.family, "video")


class TestMediaParser(unittest.TestCase):
    """Media filename parser tests."""

    def test_standard_media_filename(self):
        result = analyze("Ku.Pilih.Jalur.Langit.2026.1080p.WEB-DL.x264.AAC.mkv")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.title, "Ku Pilih Jalur Langit")
        self.assertEqual(result.entities.year, 2026)
        self.assertEqual(result.entities.resolution, "1080p")
        self.assertEqual(result.entities.source, "WEB-DL")
        self.assertEqual(result.entities.codec, "x264")
        self.assertEqual(result.entities.audio_codec, "AAC")

    def test_the_dark_knight(self):
        result = analyze("The.Dark.Knight.2008.1080p.BluRay.x264.mkv")
        self.assertEqual(result.entities.title, "The Dark Knight")
        self.assertEqual(result.entities.year, 2008)
        self.assertEqual(result.entities.resolution, "1080p")
        self.assertEqual(result.entities.source, "BluRay")

    def test_reordered_tokens(self):
        result = analyze("Movie.2026.1080p.x265.WEBRip.mkv")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.year, 2026)
        self.assertEqual(result.entities.resolution, "1080p")
        self.assertEqual(result.entities.codec, "x265")
        self.assertEqual(result.entities.source, "WEBRip")

    def test_series_pattern(self):
        result = analyze("Breaking.Bad.S05E16.1080p.BluRay.x264.mkv")
        self.assertEqual(result.entities.season, 5)
        self.assertEqual(result.entities.episode, 16)
        self.assertIn("Breaking", result.entities.title or "")

    def test_uhd_resolution(self):
        result = analyze("Film.2026.UHD.WEB-DL.mkv")
        self.assertEqual(result.entities.resolution, "2160p")

    def test_4k_resolution(self):
        result = analyze("Film.2026.4K.BluRay.mkv")
        self.assertEqual(result.entities.resolution, "2160p")


class TestGenericParser(unittest.TestCase):
    """Generic document/file parser tests."""

    def test_proposal_pdf(self):
        result = analyze("Proposal.KKN.Desa.Waindawula.2026.pdf")
        self.assertEqual(result.file_type.family, "document")
        self.assertEqual(result.entities.year, 2026)
        self.assertIn("Proposal", result.entities.title or "")
        self.assertIn("KKN", result.entities.title or "")

    def test_simple_document(self):
        result = analyze("catatan_rapat.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(result.file_type.family, "document")

    def test_audio_file(self):
        result = analyze("lagu_romantis.mp3", mime_type="audio/mpeg")
        self.assertEqual(result.file_type.family, "audio")

    def test_archive_file(self):
        result = analyze("backup_project.zip", mime_type="application/zip")
        self.assertEqual(result.file_type.family, "archive")


class TestWhatsAppParser(unittest.TestCase):
    """WhatsApp and screenshot filename tests."""

    def test_whatsapp_video(self):
        result = analyze("VID_20260929_WA0001.mp4", mime_type="video/mp4")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.year, 2026)

    def test_whatsapp_photo(self):
        result = analyze("IMG_20240815_WA0023.jpg", mime_type="image/jpeg")
        self.assertEqual(result.file_type.family, "image")
        self.assertEqual(result.entities.year, 2024)

    def test_whatsapp_audio(self):
        result = analyze("AUD-20240929-WA0003.mp3", mime_type="audio/mpeg")
        self.assertEqual(result.file_type.family, "audio")

    def test_screenshot(self):
        result = analyze("Screenshot_20240510_143000.png", mime_type="image/png")
        self.assertEqual(result.file_type.family, "image")


class TestConfidenceAndExplain(unittest.TestCase):
    """Confidence scoring and explain mode tests."""

    def test_high_confidence_video(self):
        result = analyze("Movie.2026.1080p.WEB-DL.x264.mkv", mime_type="video/x-matroska")
        self.assertIn("video", result.confidence)
        self.assertGreater(result.confidence["video"], 0.8)

    def test_high_confidence_document(self):
        result = analyze("report.pdf", mime_type="application/pdf")
        self.assertIn("document", result.confidence)
        self.assertGreater(result.confidence["document"], 0.8)

    def test_explain_mode_returns_string(self):
        result = analyze("Movie.2026.1080p.BluRay.mkv")
        explanation = result.explain()
        self.assertIsInstance(explanation, str)
        self.assertIn("Evidence chain", explanation)
        self.assertIn("Score totals", explanation)

    def test_explain_contains_signals(self):
        result = analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4")
        explanation = result.explain()
        self.assertIn("video", explanation.lower())


class TestResultSchema(unittest.TestCase):
    """Result schema and serialization tests."""

    def test_to_dict_returns_dict(self):
        result = analyze("test.mp4")
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("file_type", d)
        self.assertIn("signals", d)
        self.assertIn("evidence", d)
        self.assertIn("parser", d)

    def test_original_filename_preserved(self):
        original = "Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4"
        result = analyze(original)
        self.assertEqual(result.filename_original, original)

    def test_status_success_on_normal(self):
        result = analyze("normal_file.pdf")
        self.assertEqual(result.status, "success")

    def test_file_id_preserved(self):
        result = analyze("test.mp4", file_id=42)
        self.assertEqual(result.file_id, 42)

    def test_no_auto_move(self):
        """Verify no auto-move, auto-rename, auto-delete in result."""
        result = analyze("test.mp4")
        d = result.to_dict()
        self.assertNotIn("move_to", d)
        self.assertNotIn("rename_to", d)
        self.assertNotIn("delete", d)

    def test_null_fields_when_unknown(self):
        """NULL beats guessing."""
        result = analyze("random_file.bin")
        self.assertIsNone(result.entities.resolution)
        self.assertIsNone(result.entities.source)
        self.assertIsNone(result.entities.codec)

    def test_domain_signals_collected(self):
        result = analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4")
        self.assertIn("perusahaan", result.domain_signals)
        self.assertIn("office", result.domain_signals["perusahaan"])
        self.assertIn("weak", result.domain_signals["perusahaan"])


class TestSection38FalsePositiveProtection(unittest.TestCase):
    """Regression tests specified in Section 38 of Task 1 prompt."""

    def test_case_1_perusahaan_corporat_pdf_mp4(self):
        result = analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.year, 2026)
        self.assertEqual(result.entities.source, "WEB-DL")
        self.assertIn("Perusahaan", result.entities.title)

    def test_case_2_laporan_perusahaan_mp4(self):
        result = analyze("Laporan.Perusahaan.2026.1080p.WEB-DL.x264.mp4")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.resolution, "1080p")
        self.assertEqual(result.entities.source, "WEB-DL")

    def test_case_3_proposal_perusahaan_pdf(self):
        result = analyze("Proposal.Perusahaan.2026.pdf")
        self.assertEqual(result.file_type.family, "document")
        self.assertEqual(result.entities.year, 2026)

    def test_case_4_invoice_perusahaan_pdf(self):
        result = analyze("Invoice.Perusahaan.2026.pdf")
        self.assertEqual(result.file_type.family, "document")
        self.assertIn("invoice", result.domain_signals)
        self.assertIn("finance", result.domain_signals["invoice"])

    def test_case_5_film_penting_jpg(self):
        result = analyze("Film.Penting.Untuk.Perusahaan.jpg")
        self.assertEqual(result.file_type.family, "image")

    def test_case_6_perusahaan_mp4(self):
        result = analyze("Perusahaan.mp4")
        self.assertEqual(result.file_type.family, "video")

    def test_case_7_perusahaan_pdf(self):
        result = analyze("Perusahaan.pdf")
        self.assertEqual(result.file_type.family, "document")

    def test_case_8_the_dark_knight(self):
        result = analyze("The.Dark.Knight.2008.1080p.BluRay.x264.mkv")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.title, "The Dark Knight")
        self.assertEqual(result.entities.year, 2008)

    def test_case_9_series_pattern(self):
        result = analyze("Series.Name.S02E03.1080p.WEB-DL.mkv")
        self.assertEqual(result.file_type.family, "video")
        self.assertEqual(result.entities.season, 2)
        self.assertEqual(result.entities.episode, 3)

    def test_case_10_krs_pdf(self):
        result = analyze("KRS.2026.pdf")
        self.assertEqual(result.file_type.family, "document")
        self.assertIn("krs", result.domain_signals)
        self.assertIn("education", result.domain_signals["krs"])

    def test_negative_evidence_present(self):
        """Negative evidence signals recorded when media evidence overrides domain keywords."""
        result = analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4")
        neg_sigs = [s for s in result.signals if s.source == "negative_evidence"]
        self.assertTrue(len(neg_sigs) > 0)
        self.assertTrue(any(s.category == "office" for s in neg_sigs))


class TestFailureResilience(unittest.TestCase):
    """Intelligence failure must not break upload."""

    def test_empty_filename(self):
        result = analyze("")
        self.assertIsInstance(result, IntelligenceResult)
        self.assertIn(result.status, ("success", "partial", "failed"))

    def test_unicode_filename(self):
        result = analyze("日本語のファイル.mp4")
        self.assertIsInstance(result, IntelligenceResult)

    def test_very_long_filename(self):
        result = analyze("a" * 500 + ".mp4")
        self.assertIsInstance(result, IntelligenceResult)

    def test_special_characters(self):
        result = analyze("file [2026] (1080p) {WEB-DL}.mkv")
        self.assertIsInstance(result, IntelligenceResult)
        self.assertEqual(result.file_type.family, "video")


if __name__ == "__main__":
    unittest.main()
