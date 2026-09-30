"""Domain definitions, keyword strengths, and category resolution logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from darfin_intelligence.models import IntelligenceResult

# Supported domains
DOMAINS = [
    "media",
    "education",
    "office",
    "finance",
    "identity",
    "health",
    "legal",
    "project",
    "personal",
    "unknown",
]

# Weights
WEIGHT_STRONG = 12
WEIGHT_MODERATE = 6
WEIGHT_WEAK = 2

# Weighted keyword mappings per domain
# { domain: { "strong": set(...), "moderate": set(...), "weak": set(...) } }
DOMAIN_WEIGHTED_KEYWORDS: dict[str, dict[str, set[str]]] = {
    "education": {
        "strong": {
            "krs", "khs", "skripsi", "tesis", "disertasi", "ijazah",
            "transkrip", "silabus", "rapor", "diploma", "almamater",
        },
        "moderate": {
            "kuliah", "kampus", "tugas", "praktikum", "semester", "ujian",
            "uas", "uts", "makalah", "jurnal", "modul", "assignment",
            "course", "bootcamp", "kkn", "dosen", "guru", "mahasiswa",
            "siswa", "pr", "kuis", "webinar",
        },
        "weak": {
            "materi", "belajar", "soal", "buku", "pedoman", "panduan",
            "akademik", "pendidikan", "sekolah", "studi", "pelajaran",
        },
    },
    "office": {
        "strong": {
            "notulen", "spk", "mou", "absensi", "slip_gaji", "surat_tugas",
            "surat_keputusan", "sk", "berita_acara",
        },
        "moderate": {
            "kantor", "pegawai", "rapat", "meeting", "memo", "administrasi",
            "surat", "kontrak", "tender", "vendor", "brief", "sop",
            "karyawan", "direksi", "manajemen", "komisaris", "hrd",
        },
        "weak": {
            "perusahaan", "laporan", "dokumen", "rekap", "klien", "client",
            "internal", "divisi", "departemen", "kerja", "instansi",
            "dinas", "organisasi",
        },
    },
    "finance": {
        "strong": {
            "invoice", "kwitansi", "kuitansi", "struk", "receipt", "faktur",
            "pajak", "tax", "payslip", "kasbon", "mutasi", "rekening_koran",
        },
        "moderate": {
            "billing", "payment", "pembayaran", "transfer", "rekening",
            "gaji", "nota", "cicilan", "keuangan", "tagihan", "voucher",
            "deposit", "pembelian", "penjualan", "akuntansi",
        },
        "weak": {
            "biaya", "dana", "budget", "anggaran", "saldo", "uang",
            "harga", "kas", "finansial",
        },
    },
    "identity": {
        "strong": {
            "ktp", "sim", "paspor", "passport", "npwp", "kk", "skck",
            "bpkb", "stnk", "akta", "biodata", "kartu_keluarga",
        },
        "moderate": {
            "identitas", "cv", "resume", "bpjs", "kartu", "id_card",
            "kartu_tanda_penduduk", "surat_izin_mengemudi", "identity",
        },
        "weak": {
            "profil", "data_diri", "diri", "personal_info", "biodata_diri",
        },
    },
    "health": {
        "strong": {
            "rontgen", "resep", "diagnosa", "medcheck", "imunisasi",
            "vaksin", "swab", "antigen", "pcr", "radiologi", "mri",
        },
        "moderate": {
            "dokter", "obat", "rumah_sakit", "rs", "lab", "medical",
            "kesehatan", "terapi", "pasien", "klinik", "apotek",
            "laboratorium", "surat_sakit",
        },
        "weak": {
            "sehat", "periksa", "surat_dokter", "darah", "vitamin",
            "fisik", "gigi",
        },
    },
    "legal": {
        "strong": {
            "akta", "gugatan", "somasi", "putusan", "perkara", "advokat",
            "notaris", "peraturan", "undang_undang", "uu", "kontrak", "perjanjian",
            "surat_perjanjian", "surat_kuasa",
        },
        "moderate": {
            "izin", "legal", "hukum", "pasal", "kuasa", "litigasi",
            "arbitrase", "klausul", "perizinan", "somasi",
        },
        "weak": {
            "aturan", "kebijakan", "syarat", "ketentuan", "regulasi",
            "kebijakan_privasi", "disclaimer",
        },
    },
    "project": {
        "strong": {
            "requirements", "specification", "wireframe", "mockup",
            "sprint", "backlog", "prd", "srs", "architecture",
        },
        "moderate": {
            "project", "proyek", "proposal", "documentation", "roadmap",
            "brief", "milestone", "deliverable", "workflow", "blueprint",
        },
        "weak": {
            "desain", "plan", "draft", "revisi", "final", "v1", "v2",
            "build", "rencana", "konsep", "tahap",
        },
    },
    "media": {
        "strong": {
            "movie", "film", "series", "anime", "drakor", "drama",
            "episode", "season", "trailer", "teaser", "cinema",
        },
        "moderate": {
            "vlog", "gameplay", "streaming", "highlight", "montage",
            "fancam", "soundtrack", "ost", "clip", "video_clip",
            "konser", "rekaman_video",
        },
        "weak": {
            "video", "tonton", "rekaman", "klip", "tontonan", "media",
            "siaran", "tayangan",
        },
    },
    "personal": {
        "strong": {
            "diary", "catatan_pribadi", "rahasia", "buku_harian",
        },
        "moderate": {
            "personal", "pribadi", "keluarga", "family", "liburan",
            "vacation", "kenangan", "selfie", "reuni", "acara_keluarga",
        },
        "weak": {
            "saya", "foto", "notes", "cerita", "arsip_pribadi",
        },
    },
}


def get_token_weight(domain: str, token_lower: str) -> tuple[int, str]:
    """Return (weight, strength_label) if token matches domain, else (0, '')."""
    dom_dict = DOMAIN_WEIGHTED_KEYWORDS.get(domain)
    if not dom_dict:
        return 0, ""
    if token_lower in dom_dict["strong"]:
        return WEIGHT_STRONG, "strong"
    if token_lower in dom_dict["moderate"]:
        return WEIGHT_MODERATE, "moderate"
    if token_lower in dom_dict["weak"]:
        return WEIGHT_WEAK, "weak"
    return 0, ""


def resolve_category(result: IntelligenceResult, winning_domain: str) -> str:
    """Resolve specific category based on file family, tokens, and entities."""
    family = result.file_type.family if result.file_type else "other"
    tokens_lower = [t.lower() for t in result.tokens]
    tok_set = set(tokens_lower)

    if family == "video":
        return _resolve_video_category(result, tok_set)
    if family == "document":
        return _resolve_document_category(winning_domain, tok_set)
    if family == "image":
        return _resolve_image_category(result, winning_domain, tok_set)
    if family == "audio":
        return _resolve_audio_category(tok_set)
    if family == "archive":
        return _resolve_archive_category(tok_set)

    return f"unknown_{family}" if family != "other" else "unknown"


def _resolve_video_category(result: IntelligenceResult, tok_set: set[str]) -> str:
    if result.entities.season is not None or result.entities.episode is not None or "series" in tok_set or "drakor" in tok_set:
        return "series"
    if "anime" in tok_set:
        return "anime"
    if any(k in tok_set for k in ("tutorial", "course", "kuliah", "belajar", "training")):
        return "tutorial"
    if result.parser_name == "whatsapp_filename_parser" or any(k in tok_set for k in ("vid", "wa0001", "personal")):
        return "personal_video"
    if (result.entities.resolution or result.entities.source or result.entities.codec
            or result.entities.year or any(k in tok_set for k in ("movie", "film"))):
        return "movie"
    return "movie" if result.signals else "unknown_video"


def _resolve_document_category(domain: str, tok_set: set[str]) -> str:
    if domain == "finance":
        if any(k in tok_set for k in ("invoice", "faktur", "billing")):
            return "invoice"
        if any(k in tok_set for k in ("kwitansi", "kuitansi", "struk", "receipt")):
            return "receipt"
        if any(k in tok_set for k in ("pajak", "tax")):
            return "tax"
        if any(k in tok_set for k in ("rekening", "mutasi")):
            return "statement"
        if any(k in tok_set for k in ("gaji", "payslip")):
            return "payroll"
        return "finance_document"

    if domain == "education":
        if "krs" in tok_set:
            return "krs"
        if any(k in tok_set for k in ("skripsi", "tesis", "disertasi")):
            return "thesis"
        if any(k in tok_set for k in ("tugas", "assignment", "makalah", "praktikum")):
            return "assignment"
        if any(k in tok_set for k in ("ujian", "uas", "uts", "kuis")):
            return "exam"
        if "kkn" in tok_set:
            return "kkn"
        return "academic_document"

    if domain == "identity":
        if any(k in tok_set for k in ("ktp", "sim", "kartu")):
            return "id_card"
        if any(k in tok_set for k in ("paspor", "passport")):
            return "passport"
        if any(k in tok_set for k in ("cv", "resume", "biodata")):
            return "cv"
        return "identity_document"

    if domain == "health":
        if "resep" in tok_set:
            return "prescription"
        if any(k in tok_set for k in ("rontgen", "lab", "medcheck", "antigen", "pcr")):
            return "medical_record"
        return "health_document"

    if domain == "legal":
        if any(k in tok_set for k in ("kontrak", "perjanjian", "spk", "mou")):
            return "contract"
        if any(k in tok_set for k in ("izin", "akta")):
            return "legal_permit"
        return "legal_document"

    if domain == "project":
        if "proposal" in tok_set:
            return "proposal"
        if any(k in tok_set for k in ("specification", "requirements", "wireframe", "mockup", "blueprint")):
            return "specification"
        if any(k in tok_set for k in ("documentation", "manual", "guide")):
            return "documentation"
        return "project_document"

    if domain == "office":
        if any(k in tok_set for k in ("notulen", "minutes")):
            return "minutes"
        if any(k in tok_set for k in ("memo", "surat")):
            return "memo"
        if "laporan" in tok_set:
            return "report"
        return "administrative_document"

    if domain == "personal":
        if any(k in tok_set for k in ("diary", "catatan")):
            return "personal_note"
        return "personal_document"

    return "unknown_document"


def _resolve_image_category(result: IntelligenceResult, domain: str, tok_set: set[str]) -> str:
    if "screenshot" in tok_set or result.entities.title == "Screenshot":
        return "screenshot"
    if "poster" in tok_set:
        return "poster"
    if any(k in tok_set for k in ("scan", "scanned")) or domain in ("identity", "office", "legal"):
        return "document_image"
    if result.parser_name == "whatsapp_filename_parser" or any(k in tok_set for k in ("img", "photo", "foto", "liburan")):
        return "photo"
    ext = (result.file_type.extension_normalized or "").lower()
    if ext in ("jpg", "jpeg", "heic", "raw", "cr2", "nef", "png"):
        return "photo"
    return "unknown_image"


def _resolve_audio_category(tok_set: set[str]) -> str:
    if any(k in tok_set for k in ("voice", "ptt", "aud", "rekaman", "voice_note")):
        return "voice"
    if "podcast" in tok_set:
        return "podcast"
    if any(k in tok_set for k in ("lecture", "kuliah", "seminar")):
        return "lecture"
    if any(k in tok_set for k in ("recording", "interview")):
        return "recording"
    return "music"


def _resolve_archive_category(tok_set: set[str]) -> str:
    if any(k in tok_set for k in ("backup", "bak")):
        return "backup"
    if any(k in tok_set for k in ("project", "proyek", "src", "code", "repo", "dev", "app")):
        return "project"
    if any(k in tok_set for k in ("dokumen", "document", "docs", "laporan", "surat")):
        return "documents"
    if any(k in tok_set for k in ("setup", "install", "installer", "software")):
        return "software"
    return "unknown_archive"
