"""Rule & Dictionary based Smart Organizer for Darfin Storage.
100% offline, instant, zero external AI API keys needed.
Extensive dictionary covering Indonesian & English keywords, slang, and file types.
"""

import re
from pathlib import Path

# ── Topic Dictionary (13 Comprehensive Categories) ───────────────
TOPIC_DICTIONARY: dict[str, list[str]] = {
    "Kenangan": [
        "kenangan", "memory", "memories", "nostalgia", "keluarga", "family", "liburan",
        "holiday", "vacation", "wisata", "jalan", "trip", "tour", "travelling", "traveling",
        "pantai", "beach", "gunung", "mountain", "camping", "hiking", "curug", "piknik",
        "ultah", "ulang tahun", "birthday", "hbd", "nikah", "wedding", "pernikahan",
        "lamaran", "engagement", "wisuda", "graduation", "reuni", "reunion", "anak",
        "bayi", "baby", "bocil", "moments", "momen", "healing", "mudik", "lebaran",
        "natal", "tahun baru", "new year", "idul fitri", "ramadhan", "puasa", "bukber",
        "halal bihalal", "prewed", "prewedding", "photoshoot", "potret"
    ],
    "Keuangan & Tagihan": [
        "keuangan", "finance", "invoice", "inv", "struk", "receipt", "kwitansi", "kuitansi",
        "nota", "bon", "kasbon", "pajak", "tax", "faktur", "spt", "gaji", "slip gaji",
        "payslip", "belanja", "shopping", "alfamart", "alfamidi", "indomaret", "superindo",
        "shopee", "tokopedia", "lazada", "tiktok shop", "tagihan", "bill", "transfer",
        "tf", "bukti transfer", "mutasi", "rekening", "bank", "bca", "mandiri", "bni",
        "bri", "bsi", "jago", "dana", "gopay", "ovo", "linkaja", "spay", "qris",
        "cicilan", "bayar", "bukti bayar", "payment"
    ],
    "Kantor & Bisnis": [
        "laporan", "report", "bulanan", "mingguan", "tahunan", "kantor", "office",
        "proyek", "project", "kontrak", "contract", "spk", "mou", "pks", "perjanjian",
        "proposal", "presentasi", "ppt", "deck", "pitch", "meeting", "rapat", "notulen",
        "minutes", "absensi", "absen", "rekap", "surat", "surat masuk", "surat keluar",
        "sk", "surat tugas", "klien", "client", "kerja", "work", "brief", "sop",
        "panduan", "manual", "checklist", "tender", "vendor", "portofolio", "portfolio"
    ],
    "Pendidikan & Tugas": [
        "tugas", "assignment", "task", "kuliah", "kampus", "sekolah", "study",
        "skripsi", "tesis", "thesis", "disertasi", "makalah", "paper", "jurnal",
        "journal", "artikel", "materi", "modul", "modul ajar", "rpp", "silabus",
        "ujian", "uas", "uts", "un", "kuis", "quiz", "pr", "homework", "kursus",
        "course", "webinar", "bootcamp", "belajar", "tutorial", "rangkuman",
        "sertifikat", "certificate", "sertif", "piagam", "ijazah", "transkrip",
        "nilai", "rapor", "krs", "khs", "dosen", "guru", "praktikum", "lab"
    ],
    "Identitas & Dokumen Pribadi": [
        "ktp", "e-ktp", "sim", "paspor", "passport", "visa", "npwp", "kk",
        "kartu keluarga", "akta", "akta kelahiran", "bpjs", "kis", "skck",
        "kartu nama", "cv", "resume", "biodata", "surat lamaran", "berkas lamaran",
        "bpkb", "stnk", "polis asuransi", "dokumen penting", "pribadi"
    ],
    "Kesehatan & Medis": [
        "resep", "dokter", "obat", "rontgen", "x-ray", "lab", "hasil lab", "medcheck",
        "medical checkup", "medical check up", "check up", "checkup", "mcu", "rumah sakit",
        "rs", "klinik", "bpjs kesehatan", "surat sakit", "rawat", "imunisasi", "vaksin",
        "swab", "antigen", "pcr", "diagnosa", "terapi", "vitamin", "kesehatan", "medis",
        "pasien", "darah", "tes darah"
    ],
    "Desain & Kreatif": [
        "logo", "icon", "banner", "poster", "pamflet", "flyer", "brosur", "mockup",
        "vector", "vektor", "figma", "sketch", "canva", "psd", "photoshop", "illustrator",
        "indesign", "asset", "aset", "template", "font", "typography", "stiker",
        "sticker", "wallpaper", "header", "thumbnail", "feed", "story"
    ],
    "Musik & Audio": [
        "lagu", "song", "track", "musik", "music", "audio", "sound", "mp3", "flac",
        "wav", "podcast", "episode", "voice note", "vn", "voice", "rekaman suara",
        "instrument", "instrumental", "instrumen", "beat", "backing track", "album",
        "cover", "remix", "dj", "ringtone", "nada dering"
    ],
    "Video & Hiburan": [
        "film", "movie", "cinema", "bioskop", "trailer", "teaser", "anime", "drakor",
        "drama", "series", "serial", "k-drama", "episode", "eps", "vlog", "gameplay",
        "gaming", "stream", "streaming", "highlight", "montage", "rekaman",
        "screen recording", "youtube", "tiktok", "reel", "shorts", "fancam"
    ],
    "Aplikasi & Game": [
        "apk", "xapk", "app", "aplikasi", "software", "program", "installer", "setup",
        "patch", "mod", "cheat", "config", "cfg", "firmware", "rom", "iso", "bios",
        "emulator", "plugin", "addon", "extension", "modpack", "savegame"
    ],
    "Developer & Code": [
        "source code", "source", "script", "bot", "telegram bot", "code", "coding",
        "database", "sql", "dump", "json", "csv", "xml", "log", "env", "api",
        "html", "css", "js", "ts", "py", "python", "notebook", "ipynb", "git"
    ],
    "Buku & Komik": [
        "ebook", "e-book", "buku", "book", "novel", "komik", "comic", "manga",
        "manhwa", "manhua", "terjemahan", "pdf book", "majalah", "magazine",
        "cerpen", "puisi", "resep masakan", "bacaan"
    ],
    "Arsip & Backup": [
        "backup", "cadangan", "restore", "arsip", "archive", "zip", "rar", "7z",
        "tar", "gz", "compressed", "simpanan", "berkas lama"
    ],
}

TYPE_DEFAULT_FOLDERS: dict[str, str] = {
    "photo": "Foto",
    "video": "Video",
    "audio": "Musik",
    "document": "Dokumen",
}

# Indonesian & English month mappings
MONTH_NAMES: dict[str, str] = {
    "januari": "01", "january": "01", "jan": "01",
    "februari": "02", "february": "02", "feb": "02",
    "maret": "03", "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "mei": "05", "may": "05",
    "juni": "06", "june": "06", "jun": "06",
    "juli": "07", "july": "07", "jul": "07",
    "agustus": "08", "august": "08", "agu": "08", "agt": "08",
    "september": "09", "sep": "09", "sept": "09",
    "oktober": "10", "october": "10", "okt": "10", "oct": "10",
    "november": "11", "nov": "11",
    "desember": "12", "december": "12", "des": "12", "dec": "12",
}

SYNONYMS: dict[str, list[str]] = {
    "foto": ["img", "pic", "image", "jpg", "jpeg", "png", "camera", "photo", "selfie", "potret", "gambar", "kenangan"],
    "gambar": ["img", "pic", "image", "jpg", "jpeg", "png", "foto", "wallpaper", "poster", "logo"],
    "video": ["mp4", "mkv", "mov", "avi", "vid", "film", "movie", "klip", "clip", "cinema", "vlog", "drakor", "anime"],
    "lagu": ["mp3", "wav", "flac", "audio", "musik", "sound", "m4a", "suara", "track", "album"],
    "musik": ["mp3", "wav", "flac", "audio", "lagu", "sound", "instrumental", "beat"],
    "dokumen": ["pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "surat", "laporan", "berkas", "tugas"],
    "keuangan": ["struk", "invoice", "nota", "kwitansi", "receipt", "belanja", "bill", "pajak", "transfer", "gaji", "faktur"],
    "struk": ["invoice", "nota", "kwitansi", "receipt", "belanja", "bill", "transfer", "bukti"],
    "invoice": ["struk", "nota", "kwitansi", "receipt", "tagihan", "faktur", "bill"],
    "tugas": ["kuliah", "sekolah", "skripsi", "makalah", "jurnal", "pr", "materi", "modul", "ujian"],
    "ktp": ["sim", "paspor", "npwp", "kk", "identitas", "bpjs", "surat"],
    "buku": ["ebook", "novel", "komik", "manga", "pdf", "majalah", "cerpen"],
    "kode": ["script", "bot", "python", "py", "sql", "source", "html", "css", "js", "ts", "json"],
    "arsip": ["zip", "rar", "7z", "tar", "backup", "cadangan"],
}


def extract_year(text: str) -> str | None:
    """Extract 4-digit year (1970-2099) from filename or text."""
    # Pattern 1: Standalone 4 digits
    m = re.search(r'\b(19[7-9]\d|20[0-9]\d)\b', text)
    if m:
        return m.group(1)

    # Pattern 2: Compact date format like 20260929 or 2024-05-10
    m = re.search(r'(19[7-9]\d|20[0-9]\d)[-_]?(?:0[1-9]|1[0-2])[-_]?(?:0[1-9]|[12]\d|3[01])', text)
    if m:
        return m.group(1)

    # Pattern 3: Date with month names like 'Agustus 2024' or 'Jan-2023'
    month_regex = "|".join(MONTH_NAMES.keys())
    m = re.search(rf'(?:{month_regex})[\s_-]+(19[7-9]\d|20[0-9]\d)', text, re.IGNORECASE)
    if m:
        return m.group(1)

    return None


def detect_topic(file_name: str, file_type: str = "") -> str | None:
    """Match filename words against TOPIC_DICTIONARY keywords with scored matching."""
    stem = Path(file_name).stem.lower()
    words = re.sub(r'[^a-zA-Z0-9\s]', ' ', stem).split()
    stem_clean = " " + " ".join(words) + " "

    topic_scores: dict[str, int] = {}
    for topic, keywords in TOPIC_DICTIONARY.items():
        score = 0
        for kw in keywords:
            kw_clean = kw.lower().strip()
            if " " in kw_clean:
                if f" {kw_clean} " in stem_clean:
                    score += 20
            elif kw_clean in words or f" {kw_clean} " in stem_clean:
                score += 10

        # Type affinity boost only if at least one keyword matched
        if score > 0:
            if file_type == "video" and topic == "Video & Hiburan":
                score += 5
            elif file_type == "audio" and topic == "Musik & Audio":
                score += 5
            elif file_type == "photo" and topic in ("Kenangan", "Desain & Kreatif"):
                score += 3
            topic_scores[topic] = score


    if not topic_scores:
        return None

    sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_topics[0][0]



def suggest_folder(file_name: str, file_type: str = "document") -> tuple[str, str, str | None]:
    """Suggest an organized folder name based on topic dictionary and year.
    Returns: (suggested_folder_name, detected_topic, detected_year)
    Examples:
      'Foto Kenangan 2019.jpg' -> ('Kenangan 2019', 'Kenangan', '2019')
      'video_20260929_015229.mp4' -> ('Video 2026', 'Video', '2026')
      'Invoice Shopee Maret 2024.pdf' -> ('Keuangan & Tagihan 2024', 'Keuangan & Tagihan', '2024')
      'Skripsi Bab 1 Final.docx' -> ('Pendidikan & Tugas', 'Pendidikan & Tugas', None)
      'Resep Dokter MCU.pdf' -> ('Kesehatan & Medis', 'Kesehatan & Medis', None)
    """
    topic = detect_topic(file_name, file_type)
    year = extract_year(file_name)

    if topic:
        folder = f"{topic} {year}" if year else topic
        return folder, topic, year

    prefix = TYPE_DEFAULT_FOLDERS.get(file_type, "Koleksi File")
    folder = f"{prefix} {year}" if year else prefix
    return folder, prefix, year


def smart_rename(file_name: str) -> str:
    """Format and clean filenames into human-readable, professional names.
    Examples:
      'video_20260929_015229.mp4' -> 'Video_2026-09-29.mp4'
      'VID_20240929_WA0001.mp4'   -> 'Video_WA_2024-09-29.mp4'
      'IMG_20240815_WA0023.jpg'   -> 'Foto_WA_2024-08-15.jpg'
      'AUD-20240929-WA0003.mp3'   -> 'Audio_WA_2024-09-29.mp3'
      'PTT-20240929-WA0004.opus'  -> 'Voice_WA_2024-09-29.opus'
      'Screenshot_2024-05-10-14-30-00.png' -> 'Screenshot_2024-05-10.png'
      'foto_kenangan_liburan_bali_2019__final_bgt.jpg' -> 'Foto_Kenangan_Liburan_Bali_2019.jpg'
    """
    path = Path(file_name)
    ext = path.suffix
    stem = path.stem

    # Pattern 1: WhatsApp / Camera Video: VID_YYYYMMDD_WA... or video_YYYYMMDD_HHMMSS
    m = re.match(r'^(?:video|vid)[-_]?(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-_]wa\d+)?(?:[-_]\d+)?$', stem, re.IGNORECASE)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        tag = "_WA" if "wa" in stem.lower() else ""
        return f"Video{tag}_{y}-{mo}-{d}{ext}"

    # Pattern 2: WhatsApp / Camera Photo: IMG_YYYYMMDD_WA... or img_YYYYMMDD_HHMMSS
    m = re.match(r'^(?:img|foto|photo)[-_]?(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-_]wa\d+)?(?:[-_]\d+)?$', stem, re.IGNORECASE)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        tag = "_WA" if "wa" in stem.lower() else ""
        return f"Foto{tag}_{y}-{mo}-{d}{ext}"

    # Pattern 3: WhatsApp Audio / Voice Note: AUD-YYYYMMDD-WA... or PTT-YYYYMMDD-WA...
    m = re.match(r'^(?:aud|audio|ptt|voice)[-_]?(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-_]wa\d+)?(?:[-_]\d+)?$', stem, re.IGNORECASE)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        tag = "Voice_WA" if "ptt" in stem.lower() else "Audio_WA"
        return f"{tag}_{y}-{mo}-{d}{ext}"

    # Pattern 4: Screenshot: Screenshot_YYYYMMDD... or Screenshot_YYYY-MM-DD...
    m = re.match(r'^(?:screenshot|tangkapan[-_]?layar)[-_]?(19\d\d|20\d\d)[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])(?:[-_\d]+)?$', stem, re.IGNORECASE)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"Screenshot_{y}-{mo}-{d}{ext}"

    # Pattern 5: General messy text with redundant suffixes
    cleaned = stem
    cleaned = re.sub(r'[-_]?(?:final|fix|revisi|bgt|copy|salinan|\(\d+\)|_\d+$)', '', cleaned, flags=re.IGNORECASE)
    words = [w for w in re.split(r'[\s_.-]+', cleaned) if w]
    if not words:
        return file_name

    capitalized = [w.capitalize() if w.islower() else w for w in words]
    new_stem = "_".join(capitalized)
    return f"{new_stem}{ext}"


def get_file_tags(file_obj: dict) -> set[str]:
    """Extract all smart tags from a file (category, year, type, extension, folder, keywords)."""
    tags: set[str] = set()
    name = file_obj.get("file_name", "")
    ftype = file_obj.get("file_type", "")
    created = file_obj.get("created_at", "")

    # Extension tag (e.g. 'pdf', 'jpg', 'docx', 'mp4')
    ext = Path(name).suffix.lstrip(".").lower()
    if ext:
        tags.add(ext)

    # Type tag & type synonyms
    if ftype:
        tags.add(ftype.lower())
        if ftype == "photo":
            tags.update(["foto", "gambar", "image", "pic", "jpg", "png", "jpeg"])
        elif ftype == "video":
            tags.update(["video", "vid", "film", "movie", "mp4", "mkv"])
        elif ftype == "audio":
            tags.update(["audio", "musik", "lagu", "sound", "mp3", "flac"])
        elif ftype == "document":
            tags.update(["dokumen", "doc", "berkas", "file", "pdf", "docx", "txt", "xlsx"])

    # Year tag (from filename or created_at)
    year = extract_year(name)
    if not year and created and len(created) >= 4:
        year = created[:4]
    if year:
        tags.add(year)

    # Topic category tag (from TOPIC_DICTIONARY)
    topic = detect_topic(name, ftype)
    if topic:
        tags.add(topic.lower())
        for word in re.findall(r'\w+', topic.lower()):
            if len(word) > 2:
                tags.add(word)

    # Folder tag if available
    folder = file_obj.get("folders")
    if isinstance(folder, dict) and folder.get("name"):
        fname = folder["name"].lower()
        tags.add(fname)
        for word in re.findall(r'\w+', fname):
            if len(word) > 2:
                tags.add(word)

    # Stem words from filename
    stem = Path(name).stem.lower()
    for word in re.findall(r'\w+', stem):
        tags.add(word)

    # Custom notes and custom tags
    from utils import parse_file_metadata
    _, custom_note, custom_tags = parse_file_metadata(file_obj.get("mime_type"))
    if custom_tags:
        for t in custom_tags:
            clean_t = t.lower().lstrip("#")
            tags.add(clean_t)
            tags.add(f"#{clean_t}")
    if custom_note:
        for word in re.findall(r'\w+', custom_note.lower()):
            if len(word) > 2:
                tags.add(word)

    return tags


def smart_search(query: str, files: list[dict]) -> list[dict]:
    """Smart tag & dictionary search with multi-tag filtering (e.g. 'pdf 2024', 'keuangan 2024')."""
    q_lower = query.lower().strip()
    if not q_lower or not files:
        return []

    tokens = [t for t in re.split(r'\s+', q_lower) if t]
    if not tokens:
        return []

    scored: list[tuple[int, dict]] = []

    for f in files:
        tags = get_file_tags(f)
        name_lower = f.get("file_name", "").lower()
        exact_bonus = 100 if q_lower in name_lower else 0

        matched_tokens = 0
        token_score = 0

        for raw_tok in tokens:
            tok = raw_tok.lstrip("#")
            # Direct tag or substring match
            if tok in tags or raw_tok in tags or any(tok == tag or (len(tok) >= 3 and tok in tag) for tag in tags):
                matched_tokens += 1
                token_score += 30
            elif tok in SYNONYMS:
                syns = SYNONYMS[tok]
                if any(syn in tags or any(syn in tag for tag in tags) for syn in syns):
                    matched_tokens += 1
                    token_score += 20

        # Multi-token queries (e.g. 'pdf 2024') require all tokens to match
        if len(tokens) > 1 and matched_tokens < len(tokens):
            continue

        if matched_tokens > 0 or exact_bonus > 0:
            total_score = exact_bonus + token_score
            scored.append((total_score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored]
