"""Folder matching, normalization, and scoring engine (Task 2B)."""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.organizer.models import FolderCandidate

# Emojis and symbol cleaner
_EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff"
    r"\u2600-\u27bf"
    r"\u2300-\u23ff"
    r"\u2b50-\u2b55"
    r"\ufe0f"
    r"\u200d]+",
    re.UNICODE,
)

# Canonical domain aliases for folders
DOMAIN_FOLDER_ALIASES: dict[str, set[str]] = {
    "media": {
        "film", "movie", "movies", "cinema", "koleksi film", "video", "videos",
        "tontonan", "series", "serial", "drakor", "anime", "cinema", "bioskop",
    },
    "education": {
        "kuliah", "kampus", "college", "academic", "pendidikan", "sekolah",
        "studi", "belajar", "perkuliahan", "universitas", "tugas kuliah",
    },
    "finance": {
        "finance", "keuangan", "uang", "financial", "pembayaran", "transaksi",
        "kas", "budget", "tagihan", "faktur", "pajak",
    },
    "office": {
        "office", "kantor", "pekerjaan", "work", "kerja", "administrasi",
        "perusahaan", "tugas kantor", "surat", "laporan",
    },
    "project": {
        "project", "proyek", "projects", "tugas besar", "pengembangan",
        "dev", "code", "coding", "software",
    },
    "identity": {
        "identity", "identitas", "dokumen pribadi", "ktp", "surat pribadi",
        "data pribadi", "kyc",
    },
    "health": {
        "health", "kesehatan", "medical", "medis", "rumah sakit",
        "klinik", "resep dokter",
    },
    "legal": {
        "legal", "hukum", "dokumen hukum", "surat perjanjian", "kontrak",
    },
    "personal": {
        "personal", "pribadi", "keluarga", "family", "kenangan", "liburan",
    },
}

# Category-specific folder aliases
CATEGORY_FOLDER_ALIASES: dict[str, set[str]] = {
    "movie": {"film", "movie", "movies", "cinema", "bioskop", "film collection", "koleksi film"},
    "series": {"series", "tv series", "serial", "drama series", "drakor", "tv show"},
    "anime": {"anime", "wibu", "kartun"},
    "invoice": {"invoice", "faktur", "tagihan", "invoices"},
    "receipt": {"kwitansi", "receipt", "struk", "bukti transfer"},
    "tax": {"pajak", "tax", "spt"},
    "krs": {"krs", "kartu rencana studi", "kuliah", "perkuliahan"},
    "thesis": {"skripsi", "tesis", "tugas akhir", "ta", "disertasi"},
    "assignment": {"tugas", "tugas kuliah", "assignment", "homework", "pr"},
    "proposal": {"proposal", "proyek", "project"},
    "kkn": {"kkn", "kuliah kerja nyata"},
    "contract": {"kontrak", "perjanjian", "spk", "mou"},
    "photo": {"photo", "photos", "foto", "galeri", "gambar", "pictures"},
    "screenshot": {"screenshot", "screenshots", "tangkapan layar"},
    "music": {"music", "musik", "lagu", "songs", "audio", "soundtrack"},
    "voice": {"voice", "voice note", "rekaman suara", "suara"},
    "podcast": {"podcast", "podcasts"},
    "lecture": {"kuliah", "rekaman kuliah", "lecture", "seminar"},
    "recording": {"rekaman", "recording", "voice"},
    "backup": {"backup", "backups", "cadangan", "arsip"},
    "software": {"software", "aplikasi", "apps", "installer", "setup"},
}

# File family compatibility aliases
FAMILY_FOLDER_ALIASES: dict[str, set[str]] = {
    "video": {"film", "movie", "movies", "video", "videos", "series", "serial", "cinema", "tontonan", "anime"},
    "document": {
        "dokumen", "documents", "docs", "kuliah", "office", "kantor", "finance",
        "keuangan", "surat", "laporan", "project", "proyek", "skripsi", "tugas",
    },
    "image": {"foto", "photo", "photos", "gambar", "pictures", "screenshot", "screenshots", "galeri", "wallpaper"},
    "audio": {"musik", "music", "lagu", "songs", "audio", "sound", "podcast", "voice", "rekaman"},
    "archive": {"backup", "backups", "arsip", "archive", "zip", "project", "proyek", "software"},
}


def clean_folder_name(name: str) -> str:
    """Normalize folder name: strip emojis, symbols, extra spaces, and lowercase."""
    if not name:
        return ""
    cleaned = _EMOJI_PATTERN.sub("", name)
    cleaned = re.sub(r"[^\w\s\-_.]", "", cleaned)
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned)
    return cleaned.strip().lower()


def tokenize_folder_name(name: str) -> list[str]:
    """Tokenize folder name into individual words."""
    cleaned = clean_folder_name(name)
    return [tok for tok in cleaned.split(" ") if tok]


def build_folder_index(folders: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Build indexed lookup map with full hierarchy display paths."""
    folder_map: dict[int, dict[str, Any]] = {}
    for f in folders:
        fid = f.get("id")
        if fid is not None:
            folder_map[fid] = dict(f)

    # Compute display path for each folder
    for fid, f in folder_map.items():
        path_parts = [f.get("name", "")]
        parent_parts = []
        curr = f
        visited = {fid}
        while curr.get("parent_id") is not None:
            pid = curr["parent_id"]
            if pid in visited or pid not in folder_map:
                break
            visited.add(pid)
            parent = folder_map[pid]
            pname = parent.get("name", "")
            path_parts.insert(0, pname)
            parent_parts.insert(0, clean_folder_name(pname))
            curr = parent
        f["path"] = " / ".join(path_parts)
        f["parent_names"] = parent_parts
        f["cleaned_name"] = clean_folder_name(f.get("name", ""))
        f["tokens"] = tokenize_folder_name(f.get("name", ""))

    return folder_map


def score_folder(
    folder_entry: dict[str, Any],
    domain: str | None,
    category: str | None,
    family: str,
    context_tokens: list[str] | None = None,
) -> tuple[int, str, list[str]]:
    """Score a single user folder against file classification and context.

    Returns:
        (total_score, match_type, list_of_reasons)
    """
    score = 0
    match_type = "generic"
    reasons: list[str] = []

    f_name_clean = folder_entry["cleaned_name"]
    f_tokens = set(folder_entry["tokens"])
    path = folder_entry.get("path", "")
    is_nested = " / " in path
    parent_names = folder_entry.get("parent_names", [])

    # 1. Family Conflict Check
    if family == "video":
        # Video files should not be placed into pure document/office folders
        if any(f_name_clean == non_media for non_media in ("office", "kantor", "dokumen", "documents", "keuangan")):
            return -100, "conflict", [f"Folder '{path}' conflicts with video format"]
    elif family in ("document", "audio", "archive"):
        # Non-video files should not be placed into movie/film folders
        if f_name_clean in ("film", "movie", "movies", "cinema"):
            return -100, "conflict", [f"Folder '{path}' conflicts with {family} format"]

    cat_aliases = CATEGORY_FOLDER_ALIASES.get(category or "", set())
    dom_aliases = DOMAIN_FOLDER_ALIASES.get(domain or "", set())

    # 2. Check if parent in hierarchy matches domain/category
    parent_matches_domain = any(p in dom_aliases or p in cat_aliases for p in parent_names)

    # 3. Nested Contextual Match
    # If parent matches domain (e.g. Kuliah) and child folder matches context tokens (e.g. Pemrograman Web)
    if is_nested and parent_matches_domain and context_tokens:
        ctx_lower = {tok.lower() for tok in context_tokens}
        matching_ctx = f_tokens.intersection(ctx_lower)
        # Check if entire clean name is in context or tokens overlap
        name_in_context = any(f_name_clean in " ".join(context_tokens).lower() for _ in [0])
        if matching_ctx or name_in_context:
            score += 95
            match_type = "nested_context"
            matched_terms = matching_ctx if matching_ctx else {f_name_clean}
            reasons.append(
                f"Nested folder '{path}' matches domain via parent and course/context: {', '.join(matched_terms)} (+95)"
            )

    # 4. Exact Normalized Match (+100)
    if not match_type.startswith("nested"):
        if f_name_clean in cat_aliases:
            score += 100
            match_type = "exact"
            reasons.append(f"Folder '{path}' exact alias match for category '{category}' (+100)")
        elif f_name_clean in dom_aliases:
            score += 80
            match_type = "exact_domain"
            reasons.append(f"Folder '{path}' exact alias match for domain '{domain}' (+80)")

        # 5. Canonical Alias Match (+60)
        elif any(alias in f_name_clean for alias in cat_aliases):
            score += 60
            match_type = "alias"
            reasons.append(f"Folder '{path}' contains category alias '{category}' (+60)")
        elif any(alias in f_name_clean for alias in dom_aliases):
            score += 50
            match_type = "alias_domain"
            reasons.append(f"Folder '{path}' contains domain alias '{domain}' (+50)")

    # 6. Family Compatibility (+20)
    family_aliases = FAMILY_FOLDER_ALIASES.get(family, set())
    if f_name_clean in family_aliases or any(tok in family_aliases for tok in f_tokens) or parent_matches_domain:
        score += 20
        reasons.append(f"Folder '{path}' matches file family '{family}' (+20)")

    # 7. Token Partial Match (+15)
    token_matches = f_tokens.intersection(cat_aliases.union(dom_aliases))
    if token_matches and match_type == "generic":
        score += 15
        match_type = "token"
        reasons.append(f"Folder tokens match domain/category keywords: {', '.join(token_matches)} (+15)")

    return score, match_type, reasons
