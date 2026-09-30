"""Dictionaries — centralized alias/keyword databases for the intelligence engine.

Split by domain. Reuses pattern data from smart_organizer where sensible.
"""

from __future__ import annotations


# ── Extension → family mapping ────────────────────────────────

EXTENSION_FAMILIES: dict[str, str] = {}

_VIDEO_EXTS = [
    "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "3gp",
    "m4v", "ts", "mpg", "mpeg", "vob", "rmvb", "divx", "m2ts",
    "mts", "asf", "f4v", "ogv",
]
_IMAGE_EXTS = [
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif",
    "svg", "tiff", "tif", "ico", "raw", "cr2", "nef", "arw",
    "dng", "psd", "ai", "eps",
]
_AUDIO_EXTS = [
    "mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma",
    "alac", "aiff", "mid", "midi", "amr",
]
_DOCUMENT_EXTS = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
    "csv", "rtf", "odt", "ods", "odp", "epub", "mobi", "pages",
    "numbers", "key", "md", "json", "xml", "html", "htm",
]
_ARCHIVE_EXTS = [
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "tgz",
    "cab",
]
_APP_EXTS = [
    "apk", "xapk", "exe", "msi", "dmg", "pkg", "deb", "rpm",
    "bat", "sh", "cmd", "bin",
]

for _ext in _VIDEO_EXTS:
    EXTENSION_FAMILIES[_ext] = "video"
for _ext in _IMAGE_EXTS:
    EXTENSION_FAMILIES[_ext] = "image"
for _ext in _AUDIO_EXTS:
    EXTENSION_FAMILIES[_ext] = "audio"
for _ext in _DOCUMENT_EXTS:
    EXTENSION_FAMILIES[_ext] = "document"
for _ext in _ARCHIVE_EXTS:
    EXTENSION_FAMILIES[_ext] = "archive"
for _ext in _APP_EXTS:
    EXTENSION_FAMILIES[_ext] = "application"


# ── MIME prefix → family mapping ──────────────────────────────

MIME_FAMILY_MAP: dict[str, str] = {
    "video/": "video",
    "image/": "image",
    "audio/": "audio",
    "text/": "document",
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.oasis.opendocument": "document",
    "application/rtf": "document",
    "application/epub": "document",
    "application/json": "document",
    "application/xml": "document",
    "application/zip": "archive",
    "application/x-zip": "archive",
    "application/x-rar": "archive",
    "application/x-7z": "archive",
    "application/x-tar": "archive",
    "application/gzip": "archive",
    "application/x-bzip": "archive",
    "application/x-xz": "archive",
    "application/x-iso9660": "archive",
    "application/vnd.android.package-archive": "application",
    "application/x-msdownload": "application",
    "application/x-executable": "application",
    "application/octet-stream": "other",
}


def mime_to_family(mime_type: str | None) -> str | None:
    """Resolve MIME type to file family."""
    if not mime_type:
        return None
    mime = mime_type.lower().strip()
    # Exact matches first
    if mime in MIME_FAMILY_MAP:
        return MIME_FAMILY_MAP[mime]
    # Prefix matches
    for prefix, family in MIME_FAMILY_MAP.items():
        if prefix.endswith("/") and mime.startswith(prefix):
            return family
        if mime.startswith(prefix):
            return family
    return None


# ── Domain keyword dictionaries ──────────────────────────────

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "education": [
        "kuliah", "tugas", "krs", "khs", "skripsi", "tesis", "disertasi",
        "praktikum", "ujian", "semester", "makalah", "jurnal", "modul",
        "silabus", "uas", "uts", "kuis", "bootcamp", "sertifikat",
        "ijazah", "transkrip", "rapor", "dosen", "guru", "assignment",
        "thesis", "course", "webinar", "kkn", "proposal",
    ],
    "office": [
        "perusahaan", "kantor", "pegawai", "rapat", "meeting",
        "administrasi", "surat", "memo", "kontrak", "spk", "mou",
        "notulen", "absensi", "rekap", "tender", "vendor",
        "presentasi", "brief", "sop", "klien", "client",
    ],
    "finance": [
        "invoice", "kwitansi", "kuitansi", "struk", "receipt",
        "billing", "payment", "transfer", "pajak", "tax", "faktur",
        "gaji", "payslip", "nota", "kasbon", "cicilan", "mutasi",
    ],
    "media": [
        "movie", "film", "series", "episode", "season", "anime",
        "drakor", "drama", "vlog", "gameplay", "streaming",
        "highlight", "montage", "fancam", "trailer", "teaser",
    ],
    "identity": [
        "ktp", "sim", "paspor", "passport", "npwp", "kk", "akta",
        "bpjs", "skck", "cv", "resume", "biodata", "bpkb", "stnk",
    ],
    "health": [
        "resep", "dokter", "rontgen", "medcheck", "diagnosa", "terapi",
        "imunisasi", "vaksin", "swab", "antigen", "pcr",
    ],
}


# ── Strong media technical signals ────────────────────────────
# Presence of ANY of these in filename tokens = strong media evidence

MEDIA_TECHNICAL_SIGNALS: set[str] = {
    "1080p", "720p", "480p", "360p", "2160p", "4k", "8k",
    "uhd", "fhd", "hd", "hdr", "hdr10",
    "web-dl", "webdl", "webrip", "bluray", "blu-ray",
    "brrip", "bdrip", "hdrip", "dvdrip", "hdtv",
    "remux", "cam", "telesync",
    "x264", "x265", "h264", "h265", "h.264", "h.265",
    "hevc", "avc", "av1", "vp9",
    "aac", "ac3", "eac3", "dts", "truehd", "atmos",
    "dolby", "imax",
    "proper", "repack", "internal",
    "extended", "unrated", "directors",
    "dual", "multi",
}

# Series patterns (S01E01, Season 1, etc.)
SERIES_PATTERNS = [
    r'[Ss](\d{1,2})[Ee](\d{1,3})',  # S01E01
    r'[Ss]eason[\s._-]?(\d{1,2})[\s._-]?[Ee]pisode[\s._-]?(\d{1,3})',
    r'[Ss](\d{1,2})',  # S01 alone
    r'[Ee](\d{1,3})',  # E01 alone (weaker)
]
