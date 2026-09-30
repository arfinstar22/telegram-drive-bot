"""Comprehensive test suite for darfin_intelligence.organizer (Task 2B).

Covers:
- All required cases from Section 31
- False-positive folder protection (Section 32)
- User-specific folder reuse without hardcoding (Section 33)
- Root vs. nested folder hierarchy & context (Section 34)
- Case and duplicate normalization (Section 35)
- Ambiguity detection (Section 36)
- No match handling without auto-creating folders (Section 37)
- Domain and category-specific mapping
- Explainability and serialization
- Performance benchmark (1,000 classifications x 100 folders)
"""

import time
import unittest

from darfin_intelligence import analyze, classify, map_folder
from darfin_intelligence.classifier.models import ClassificationResult
from darfin_intelligence.organizer import FolderMapper, FolderSuggestion


class TestSection31RequiredCases(unittest.TestCase):
    """Section 31: Mandatory acceptance test cases."""

    def test_media_movie_prefers_film_or_movies_over_office(self):
        c = classify(analyze("The.Matrix.1999.1080p.mkv"))
        folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Office", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Film")

    def test_finance_invoice_prefers_keuangan(self):
        c = classify(analyze("Invoice_Tagihan_Hosting_2026.pdf"))
        folders = [
            {"id": 10, "name": "Keuangan", "parent_id": None},
            {"id": 11, "name": "Kuliah", "parent_id": None},
            {"id": 12, "name": "Film", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Keuangan")

    def test_education_krs_prefers_kuliah(self):
        c = classify(analyze("KRS_Semester_Genap_2026.pdf"))
        folders = [
            {"id": 20, "name": "Kuliah", "parent_id": None},
            {"id": 21, "name": "Finance", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Kuliah")

    def test_media_movie_with_office_and_dokumen_returns_no_match(self):
        c = classify(analyze("Avengers.Endgame.1080p.mkv"))
        folders = [
            {"id": 30, "name": "Office", "parent_id": None},
            {"id": 31, "name": "Dokumen", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "no_match")
        self.assertIsNone(s.target_folder_id)


class TestFalsePositiveFolderProtection(unittest.TestCase):
    """Section 32: Critical false positive benchmark."""

    def test_perusahaan_corporat_pdf_mp4_selects_film_not_office(self):
        # File has 'perusahaan' keyword, but is technically a video (media/movie)
        c = classify(analyze("Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4"))
        folders = [
            {"id": 40, "name": "Office", "parent_id": None},
            {"id": 41, "name": "Film", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Film")
        self.assertNotEqual(s.target_folder_name, "Office")

    def test_laporan_video_selects_movies_not_laporan(self):
        c = classify(analyze("Laporan.Perusahaan.2026.1080p.WEB-DL.x264.mp4"))
        folders = [
            {"id": 50, "name": "Laporan Tahunan", "parent_id": None},
            {"id": 51, "name": "Movies", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Movies")


class TestUserSpecificFolderReuse(unittest.TestCase):
    """Section 33: Adapts dynamically to each user's existing folder names."""

    def test_user_a_and_user_b_reuse_actual_folders(self):
        c = classify(analyze("Interstellar.2014.1080p.mkv"))

        # User A uses Indonesian folder names
        folders_user_a = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Kuliah", "parent_id": None},
            {"id": 3, "name": "Keuangan", "parent_id": None},
        ]
        s_a = map_folder(c, folders_user_a)
        self.assertEqual(s_a.target_folder_name, "Film")

        # User B uses English folder names
        folders_user_b = [
            {"id": 101, "name": "Movies", "parent_id": None},
            {"id": 102, "name": "College", "parent_id": None},
            {"id": 103, "name": "Finance", "parent_id": None},
        ]
        s_b = map_folder(c, folders_user_b)
        self.assertEqual(s_b.target_folder_name, "Movies")

    def test_koleksi_film_alias_reused(self):
        c = classify(analyze("Movie.1080p.mkv"))
        folders = [{"id": 5, "name": "Koleksi Film Favorit", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Koleksi Film Favorit")


class TestNestedFolderHierarchy(unittest.TestCase):
    """Section 34: Root vs child folder priority and context matching."""

    def test_nested_course_folder_ranked_higher_than_root(self):
        c = classify(analyze("Tugas_Pemrograman_Web.docx"))
        folders = [
            {"id": 1, "name": "Kuliah", "parent_id": None},
            {"id": 2, "name": "Pemrograman Web", "parent_id": 1},
            {"id": 3, "name": "Basis Data", "parent_id": 1},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "Pemrograman Web")
        self.assertEqual(s.target_folder_path, "Kuliah / Pemrograman Web")
        self.assertEqual(s.target_folder_id, 2)

    def test_nested_path_displayed_accurately(self):
        c = classify(analyze("Modul_Praktikum_Basis_Data.pdf"))
        folders = [
            {"id": 10, "name": "Kuliah", "parent_id": None},
            {"id": 11, "name": "Semester 3", "parent_id": 10},
            {"id": 12, "name": "Basis Data", "parent_id": 11},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_path, "Kuliah / Semester 3 / Basis Data")


class TestNormalizationAndDuplicates(unittest.TestCase):
    """Section 35: Deduplicate case variants and strip emoji noise."""

    def test_emoji_in_folder_name_stripped_cleanly(self):
        c = classify(analyze("Inception.1080p.mkv"))
        folders = [{"id": 1, "name": "🎬 Film", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        self.assertEqual(s.target_folder_name, "🎬 Film")

    def test_duplicate_case_folders_dont_pollute_candidates(self):
        c = classify(analyze("Avatar.1080p.mkv"))
        folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "film", "parent_id": None},
            {"id": 3, "name": "FILM", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "matched")
        # Should only have 1 unique candidate because duplicates under same parent are collapsed
        self.assertEqual(len(s.candidates), 1)


class TestAmbiguityAndNoMatch(unittest.TestCase):
    """Section 36 & 37: Ambiguity detection and no-match handling."""

    def test_tied_film_and_movies_returns_ambiguous(self):
        c = classify(analyze("The.Godfather.1080p.mkv"))
        folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Movies", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "ambiguous")
        self.assertIsNone(s.target_folder_id)
        self.assertGreaterEqual(len(s.candidates), 2)

    def test_unmatched_domain_returns_no_match(self):
        # Health domain with unrelated user folders
        c = classify(analyze("Hasil_Rontgen_Pasien_2026.pdf"))
        folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Kuliah", "parent_id": None},
            {"id": 3, "name": "Projects", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.status, "no_match")
        self.assertIsNone(s.target_folder_id)

    def test_empty_folders_list_returns_no_match(self):
        c = classify(analyze("Any_File.pdf"))
        s = map_folder(c, [])
        self.assertEqual(s.status, "no_match")
        self.assertIsNone(s.target_folder_id)


class TestSpecificDomainMappings(unittest.TestCase):
    """Domain and category specific mappings."""

    def test_identity_document_maps_to_dokumen_pribadi(self):
        c = classify(analyze("Scan_KTP_Darfin.pdf"))
        folders = [
            {"id": 1, "name": "Dokumen Pribadi", "parent_id": None},
            {"id": 2, "name": "Kuliah", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Dokumen Pribadi")

    def test_legal_contract_maps_to_dokumen_hukum(self):
        c = classify(analyze("Surat_Perjanjian_Kerjasama.pdf"))
        folders = [
            {"id": 1, "name": "Dokumen Hukum", "parent_id": None},
            {"id": 2, "name": "Office", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Dokumen Hukum")

    def test_health_record_maps_to_kesehatan(self):
        c = classify(analyze("Hasil_Lab_Kesehatan_2026.pdf"))
        folders = [
            {"id": 1, "name": "Kesehatan", "parent_id": None},
            {"id": 2, "name": "Office", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Kesehatan")

    def test_project_proposal_maps_to_proyek(self):
        c = classify(analyze("Proposal_Pengembangan_Aplikasi.docx"))
        folders = [
            {"id": 1, "name": "Proyek", "parent_id": None},
            {"id": 2, "name": "Kantor", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Proyek")

    def test_screenshot_maps_to_screenshots(self):
        c = classify(analyze("Screenshot_20260930_120000.png"))
        folders = [
            {"id": 1, "name": "Screenshots", "parent_id": None},
            {"id": 2, "name": "Film", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Screenshots")

    def test_podcast_maps_to_podcasts(self):
        c = classify(analyze("Podcast_Teknologi_Ep01.mp3"))
        folders = [
            {"id": 1, "name": "Podcast", "parent_id": None},
            {"id": 2, "name": "Film", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Podcast")

    def test_backup_maps_to_cadangan(self):
        c = classify(analyze("Backup_Server_2026.zip"))
        folders = [
            {"id": 1, "name": "Cadangan", "parent_id": None},
            {"id": 2, "name": "Proyek", "parent_id": None},
        ]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Cadangan")


class TestClassInterfaceAndExplain(unittest.TestCase):
    """Class interface, explainability, and serialization."""

    def test_folder_mapper_class_matches_function(self):
        c = classify(analyze("Movie.1080p.mkv"))
        folders = [{"id": 1, "name": "Film", "parent_id": None}]
        s1 = map_folder(c, folders)
        s2 = FolderMapper.map_folder(c, folders)
        self.assertEqual(s1.target_folder_id, s2.target_folder_id)

    def test_explain_contains_key_reasons(self):
        c = classify(analyze("Invoice_Perusahaan.pdf"))
        folders = [{"id": 1, "name": "Keuangan", "parent_id": None}]
        s = map_folder(c, folders)
        explanation = s.explain()
        self.assertIn("Folder Suggestion Status: MATCHED", explanation)
        self.assertIn("Keuangan", explanation)

    def test_to_dict_structure(self):
        c = classify(analyze("Invoice.pdf"))
        folders = [{"id": 1, "name": "Keuangan", "parent_id": None}]
        s = map_folder(c, folders)
        d = s.to_dict()
        self.assertIn("status", d)
        self.assertIn("target", d)
        self.assertEqual(d["target"]["name"], "Keuangan")


class TestAdditionalDomainAndDeterminism(unittest.TestCase):
    """Section 41 & 42: Determinism and additional domain coverage."""

    def test_audio_lecture_maps_to_kuliah(self):
        c = classify(analyze("Rekaman_Kuliah_AI.m4a"))
        folders = [{"id": 1, "name": "Kuliah", "parent_id": None}, {"id": 2, "name": "Film", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Kuliah")

    def test_audio_voice_maps_to_voice(self):
        c = classify(analyze("Voice_Note_001.opus"))
        folders = [{"id": 1, "name": "Voice Notes", "parent_id": None}, {"id": 2, "name": "Film", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Voice Notes")

    def test_archive_software_maps_to_software(self):
        c = classify(analyze("VSCode_Setup_2026.zip"))
        folders = [{"id": 1, "name": "Software", "parent_id": None}, {"id": 2, "name": "Kuliah", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Software")

    def test_document_thesis_maps_to_skripsi(self):
        c = classify(analyze("Skripsi_Final_Revision.pdf"))
        folders = [{"id": 1, "name": "Skripsi", "parent_id": None}, {"id": 2, "name": "Keuangan", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Skripsi")

    def test_document_tax_maps_to_pajak(self):
        c = classify(analyze("Bukti_Pajak_Tahunan.pdf"))
        folders = [{"id": 1, "name": "Pajak", "parent_id": None}, {"id": 2, "name": "Kuliah", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Pajak")

    def test_image_photo_maps_to_galeri(self):
        c = classify(analyze("Liburan_Bali_2026.jpg"))
        folders = [{"id": 1, "name": "Galeri", "parent_id": None}, {"id": 2, "name": "Dokumen", "parent_id": None}]
        s = map_folder(c, folders)
        self.assertEqual(s.target_folder_name, "Galeri")

    def test_determinism_same_input_same_output(self):
        c = classify(analyze("Invoice_Perusahaan.pdf"))
        folders = [{"id": 1, "name": "Keuangan", "parent_id": None}, {"id": 2, "name": "Office", "parent_id": None}]
        s1 = map_folder(c, folders)
        s2 = map_folder(c, folders)
        self.assertEqual(s1.target_folder_id, s2.target_folder_id)
        self.assertEqual(s1.confidence, s2.confidence)
        self.assertEqual(s1.reasons, s2.reasons)

    def test_stable_tie_break_ordering(self):
        c = classify(analyze("Unknown_File.bin"))
        folders = [{"id": 2, "name": "Random_B", "parent_id": None}, {"id": 1, "name": "Random_A", "parent_id": None}]
        s1 = map_folder(c, folders)
        s2 = map_folder(c, folders)
        self.assertEqual(s1.status, s2.status)


class TestPerformanceBenchmark(unittest.TestCase):
    """Section 40: Benchmark 1,000 files against 100 folders."""

    def test_1000_files_100_folders_throughput(self):
        folders = []
        for i in range(1, 71):
            folders.append({"id": i, "name": f"Folder_{i}", "parent_id": None})
        folders.append({"id": 71, "name": "Film", "parent_id": None})
        folders.append({"id": 72, "name": "Keuangan", "parent_id": None})
        folders.append({"id": 73, "name": "Kuliah", "parent_id": None})
        for i in range(74, 101):
            folders.append({"id": i, "name": f"Subfolder_{i}", "parent_id": (i % 3) + 71})

        samples = [
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
        classifications = [classify(analyze(samples[i % len(samples)])) for i in range(1000)]
        from darfin_intelligence.organizer import build_folder_index
        folder_index = build_folder_index(folders)

        start_time = time.monotonic()
        for c in classifications:
            res = map_folder(c, folder_index)
            self.assertIsNotNone(res.status)
        elapsed = time.monotonic() - start_time

        # 1,000 files against 100 folders indexed runs in under 0.50s
        self.assertLess(elapsed, 0.50, f"1000 classifications x 100 folders took: {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
