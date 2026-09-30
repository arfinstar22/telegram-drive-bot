"""Comprehensive test suite for darfin_intelligence.classifier (Task 2A).

Covers:
- All 10 mandatory benchmark cases (Section 24)
- Strong technical evidence vs weak keyword conflict resolution (Section 25)
- Ambiguity detection and candidate scoring (Section 26)
- Specific domains: media, education, office, finance, identity, health, legal, project, personal
- File families: video, document, image, audio, archive
- Confidence calculation and explainability
- High-throughput performance benchmark (1,000 files)
"""

import time
import unittest

from darfin_intelligence import analyze, classify
from darfin_intelligence.classifier import DomainClassifier, ClassificationResult


class TestRequiredCasesSection24(unittest.TestCase):
    """The 10 mandatory regression scenarios from prompt Section 24."""

    def test_case_1_perusahaan_corporat_pdf_mp4(self):
        res = classify(analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4"))
        self.assertEqual(res.family, "video")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "movie")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.95)
        self.assertIn("perusahaan", res.explain().lower())

    def test_case_2_laporan_perusahaan_mp4(self):
        res = classify(analyze("Laporan.Perusahaan.2026.1080p.WEB-DL.x264.mp4"))
        self.assertEqual(res.family, "video")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "movie")
        self.assertEqual(res.status, "classified")

    def test_case_3_proposal_perusahaan_pdf(self):
        res = classify(analyze("Proposal.Perusahaan.2026.pdf"))
        self.assertEqual(res.family, "document")
        self.assertEqual(res.domain, "project")
        self.assertEqual(res.category, "proposal")
        self.assertEqual(res.status, "classified")

    def test_case_4_invoice_perusahaan_pdf(self):
        res = classify(analyze("Invoice.Perusahaan.2026.pdf"))
        self.assertEqual(res.family, "document")
        self.assertEqual(res.domain, "finance")
        self.assertEqual(res.category, "invoice")
        self.assertEqual(res.status, "classified")
        self.assertGreaterEqual(res.confidence, 0.80)

    def test_case_5_film_penting_jpg(self):
        res = classify(analyze("Film.Penting.Untuk.Perusahaan.jpg"))
        self.assertEqual(res.family, "image")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "photo")
        self.assertEqual(res.status, "classified")

    def test_case_6_perusahaan_mp4(self):
        res = classify(analyze("Perusahaan.mp4"))
        self.assertEqual(res.family, "video")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "movie")
        self.assertEqual(res.status, "classified")

    def test_case_7_perusahaan_pdf(self):
        res = classify(analyze("Perusahaan.pdf"))
        self.assertEqual(res.family, "document")
        self.assertEqual(res.domain, "office")
        self.assertEqual(res.status, "classified")

    def test_case_8_the_dark_knight(self):
        res = classify(analyze("The.Dark.Knight.2008.1080p.BluRay.x264.mkv"))
        self.assertEqual(res.family, "video")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "movie")
        self.assertEqual(res.status, "classified")

    def test_case_9_series_pattern(self):
        res = classify(analyze("Series.Name.S02E03.1080p.WEB-DL.mkv"))
        self.assertEqual(res.family, "video")
        self.assertEqual(res.domain, "media")
        self.assertEqual(res.category, "series")
        self.assertEqual(res.status, "classified")

    def test_case_10_krs_pdf(self):
        res = classify(analyze("KRS.2026.pdf"))
        self.assertEqual(res.family, "document")
        self.assertEqual(res.domain, "education")
        self.assertEqual(res.category, "krs")
        self.assertEqual(res.status, "classified")
        self.assertEqual(res.confidence, 1.0)


class TestConflictResolution(unittest.TestCase):
    """Section 25: Technical media signals must override weak keyword signals."""

    def test_office_keyword_with_video_technical_evidence(self):
        res = classify(analyze("Rapat.Direksi.2026.720p.HDTV.x264.mkv"))
        self.assertEqual(res.domain, "media")
        self.assertNotEqual(res.domain, "office")

    def test_education_keyword_with_video_technical_evidence(self):
        res = classify(analyze("Kuliah.Umum.Semester.5.1080p.BluRay.mkv"))
        self.assertEqual(res.domain, "media")
        self.assertNotEqual(res.domain, "education")

    def test_finance_keyword_with_video_container(self):
        res = classify(analyze("Invoice.Pelanggan.2026.mp4"))
        self.assertEqual(res.domain, "media")
        self.assertNotEqual(res.domain, "finance")

    def test_media_keyword_inside_pdf_does_not_become_movie(self):
        res = classify(analyze("Analisis.Film.Dokumenter.2026.pdf"))
        self.assertEqual(res.family, "document")
        self.assertNotEqual(res.category, "movie")

    def test_class_interface_matches_function(self):
        raw = analyze("Movie.1080p.mkv")
        res1 = classify(raw)
        res2 = DomainClassifier.classify(raw)
        self.assertEqual(res1.domain, res2.domain)
        self.assertEqual(res1.category, res2.category)


class TestAmbiguityDetection(unittest.TestCase):
    """Section 26: Ambiguity and low confidence detection."""

    def test_tied_candidates_marked_ambiguous(self):
        # "Proposal" is project (+6), "KKN" is education (+6)
        res = classify(analyze("Proposal.KKN.2026.pdf"))
        self.assertEqual(res.status, "ambiguous")
        self.assertIsNone(res.domain)
        self.assertIsNone(res.category)
        self.assertGreaterEqual(len(res.top_candidates), 2)
        top_domains = {c["domain"] for c in res.top_candidates[:2]}
        self.assertEqual(top_domains, {"education", "project"})

    def test_generic_document_has_dampened_confidence(self):
        # "Dokumen.2026.pdf" only has weak keyword
        res = classify(analyze("Dokumen.2026.pdf"))
        self.assertLessEqual(res.confidence, 0.50)

    def test_pure_numbers_pdf_is_unknown(self):
        res = classify(analyze("123456789.pdf"))
        self.assertEqual(res.status, "unknown")
        self.assertIsNone(res.domain)
        self.assertEqual(res.category, "unknown_document")
        self.assertEqual(res.confidence, 0.0)

    def test_empty_string_filename_resilience(self):
        res = classify(analyze(""))
        self.assertIn(res.status, ("unknown", "failed", "classified"))

    def test_candidates_sorted_descending(self):
        res = classify(analyze("Proposal.Perusahaan.2026.pdf"))
        scores = [c["score"] for c in res.top_candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestDomainEducation(unittest.TestCase):
    """Education domain classification and categories."""

    def test_skripsi_is_thesis(self):
        res = classify(analyze("Skripsi_Teknik_Informatika_2026.pdf"))
        self.assertEqual(res.domain, "education")
        self.assertEqual(res.category, "thesis")
        self.assertEqual(res.status, "classified")

    def test_tugas_is_assignment(self):
        res = classify(analyze("Tugas_Matematika_Diskrit.docx"))
        self.assertEqual(res.domain, "education")
        self.assertEqual(res.category, "assignment")

    def test_ujian_is_exam(self):
        res = classify(analyze("Soal_UTS_Algoritma_2026.pdf"))
        self.assertEqual(res.domain, "education")
        self.assertEqual(res.category, "exam")


class TestDomainFinance(unittest.TestCase):
    """Finance domain classification and categories."""

    def test_kwitansi_is_receipt(self):
        res = classify(analyze("Kwitansi_Pembelian_Buku_2026.pdf"))
        self.assertEqual(res.domain, "finance")
        self.assertEqual(res.category, "receipt")

    def test_pajak_is_tax(self):
        res = classify(analyze("Bukti_Potong_Pajak_SPT_2026.pdf"))
        self.assertEqual(res.domain, "finance")
        self.assertEqual(res.category, "tax")

    def test_slip_gaji_is_payroll(self):
        res = classify(analyze("Slip_Gaji_September_2026.pdf"))
        self.assertEqual(res.domain, "finance")
        self.assertEqual(res.category, "payroll")


class TestDomainOffice(unittest.TestCase):
    """Office domain classification and categories."""

    def test_notulen_is_minutes(self):
        res = classify(analyze("Notulen_Rapat_Bulanan_2026.docx"))
        self.assertEqual(res.domain, "office")
        self.assertEqual(res.category, "minutes")

    def test_memo_is_memo(self):
        res = classify(analyze("Memo_Internal_Direksi_2026.pdf"))
        self.assertEqual(res.domain, "office")
        self.assertEqual(res.category, "memo")

    def test_laporan_is_report(self):
        res = classify(analyze("Laporan_Tahunan_Divisi_SDM_2026.pdf"))
        self.assertEqual(res.domain, "office")
        self.assertEqual(res.category, "report")


class TestDomainIdentity(unittest.TestCase):
    """Identity domain classification and categories."""

    def test_ktp_is_id_card(self):
        res = classify(analyze("KTP_Darfin_Star.pdf"))
        self.assertEqual(res.domain, "identity")
        self.assertEqual(res.category, "id_card")

    def test_paspor_is_passport(self):
        res = classify(analyze("Paspor_Scan_2026.pdf"))
        self.assertEqual(res.domain, "identity")
        self.assertEqual(res.category, "passport")

    def test_cv_is_cv(self):
        res = classify(analyze("CV_Resume_Software_Engineer.pdf"))
        self.assertEqual(res.domain, "identity")
        self.assertEqual(res.category, "cv")


class TestDomainHealthAndLegal(unittest.TestCase):
    """Health and legal domain classifications."""

    def test_rontgen_is_health(self):
        res = classify(analyze("Hasil_Rontgen_Dada_2026.pdf"))
        self.assertEqual(res.domain, "health")
        self.assertEqual(res.category, "medical_record")

    def test_resep_dokter_is_health(self):
        res = classify(analyze("Resep_Dokter_Klinik.pdf"))
        self.assertEqual(res.domain, "health")
        self.assertEqual(res.category, "prescription")

    def test_surat_perjanjian_is_legal(self):
        res = classify(analyze("Surat_Perjanjian_Sewa_Rumah.pdf"))
        self.assertEqual(res.domain, "legal")
        self.assertEqual(res.category, "contract")


class TestImageAudioArchiveFamilies(unittest.TestCase):
    """Image, audio, and archive family classifications."""

    def test_screenshot_png(self):
        res = classify(analyze("Screenshot_20260930_142000.png"))
        self.assertEqual(res.family, "image")
        self.assertEqual(res.category, "screenshot")

    def test_scanned_ktp_image(self):
        res = classify(analyze("Scan_KTP_Asli.jpg"))
        self.assertEqual(res.family, "image")
        self.assertEqual(res.domain, "identity")
        self.assertIn(res.category, ("scan", "document_image"))

    def test_voice_note_opus(self):
        res = classify(analyze("Voice_Note_001.opus"))
        self.assertEqual(res.family, "audio")
        self.assertEqual(res.category, "voice")

    def test_podcast_mp3(self):
        res = classify(analyze("Podcast_Teknologi_Ep12.mp3"))
        self.assertEqual(res.family, "audio")
        self.assertEqual(res.category, "podcast")

    def test_backup_zip(self):
        res = classify(analyze("Backup_Database_20260930.zip"))
        self.assertEqual(res.family, "archive")
        self.assertEqual(res.category, "backup")

    def test_project_zip(self):
        res = classify(analyze("Project_Telegram_Bot_Src.zip"))
        self.assertEqual(res.family, "archive")
        self.assertEqual(res.category, "project")


class TestExplainAndSerialization(unittest.TestCase):
    """Explain mode and serialization verification."""

    def test_to_dict_contains_all_fields(self):
        res = classify(analyze("Invoice.Perusahaan.2026.pdf"))
        d = res.to_dict()
        self.assertIn("domain", d)
        self.assertIn("category", d)
        self.assertIn("status", d)
        self.assertIn("confidence", d)
        self.assertIn("scores", d)
        self.assertIn("evidence", d)
        self.assertIn("top_candidates", d)

    def test_explain_contains_key_elements(self):
        res = classify(analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4"))
        exp = res.explain()
        self.assertIn("Candidate scores:", exp)
        self.assertIn("Evidence breakdown:", exp)
        self.assertIn("Decision: domain=media", exp)


class TestBenchmarkPerformance(unittest.TestCase):
    """Section 28: Benchmark classification throughput for 1,000 files."""

    def test_classify_1000_files_performance(self):
        sample_filenames = [
            "Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4",
            "Invoice.Perusahaan.2026.pdf",
            "KRS.Semester.3.2026.pdf",
            "Screenshot_20260930_120000.png",
            "Podcast_Episode_01.mp3",
            "Backup_Laptop_2026.zip",
            "Surat_Perjanjian_Kerjasama.pdf",
            "Hasil_Rontgen_Pasien.pdf",
            "The.Matrix.1999.1080p.BluRay.x264.mkv",
            "Tugas_Besar_Pemrograman_Web.docx",
        ]
        # Generate 1,000 IntelligenceResult objects
        results = [analyze(sample_filenames[i % len(sample_filenames)]) for i in range(1000)]

        start_time = time.monotonic()
        for r in results:
            cls = classify(r)
            self.assertIsNotNone(cls.status)
        elapsed = time.monotonic() - start_time

        # 1,000 classifications must finish in under 0.25 seconds
        self.assertLess(elapsed, 0.25, f"1000 classifications took too long: {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
