"""Generic and formal document parsing engine for Task 3C.

Identifies document types (official letter, invoice, academic document, bank statement,
proposal, certificate, contract, report, form) and extracts structured metadata fields.
"""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.document.amounts import extract_all_standalone_amounts, extract_labeled_amounts
from darfin_intelligence.document.dates import extract_document_dates, extract_labeled_date
from darfin_intelligence.document.models import DocumentData
from darfin_intelligence.document.normalizer import clean_document_text

DOCUMENT_TYPE_RULES: list[tuple[str, list[tuple[str, int]]]] = [
    # official_letter: formal Indonesian administrative letter
    (
        "official_letter",
        [
            (r"\b(nomor:|no\.:|nomor\s+surat:)", 12),
            (r"\b(perihal:|hal:)", 10),
            (r"\b(lampiran:)", 8),
            (r"\b(kepada\s+yth|dengan\s+hormat)\b", 12),
            (r"\b(surat\s+keputusan|surat\s+tugas|surat\s+edaran|surat\s+permohonan)\b", 12),
            (r"\b(menimbang|mengingat|memutuskan)\b", 12),
        ],
    ),
    # invoice: commercial billing
    (
        "invoice",
        [
            (r"\b(invoice|tagihan)\b", 14),
            (r"\b(invoice\s+number|no\.\s*invoice|no\.\s*faktur|faktur\s+pajak)", 12),
            (r"\b(bill\s+to|tagihan\s+kepada)", 10),
            (r"\b(due\s+date|jatuh\s+tempo)", 10),
            (r"\b(payment\s+terms|syarat\s+pembayaran)\b", 8),
        ],
    ),
    # academic_document: university / school
    (
        "academic_document",
        [
            (r"\b(krs|khs|kartu\s+rencana\s+studi|kartu\s+hasil\s+studi)\b", 16),
            (r"\b(transkrip\s+nilai|transkrip\s+akademik)\b", 14),
            (r"\b(npm|nim|nisn)\b", 10),
            (r"\b(mata\s+kuliah|matkul|sks)\b", 10),
            (r"\b(semester|fakultas|program\s+studi|prodi)\b", 8),
            (r"\b(dosen\s+pembimbing|dekan|rektor)\b", 8),
        ],
    ),
    # bank_document / statement: bank transaction / account statement
    (
        "bank_document",
        [
            (r"\b(mutasi\s+rekening|rekening\s+koran|statement\s+of\s+account)\b", 14),
            (r"\b(rekening\s+tujuan|nominal\s+transfer|transfer\s+berhasil)\b", 12),
            (r"\b(saldo\s+awal|saldo\s+akhir|saldo\s+rekening)\b", 12),
            (r"\b(m-bca|klikbca|livin|brimo|bni\s+mobile)\b", 10),
            (r"\b(debit|kredit|debet|cr|db)\b", 6),
        ],
    ),
    # proposal: project/event proposal
    (
        "proposal",
        [
            (r"\b(proposal\s+kegiatan|proposal\s+penelitian|proposal\s+usaha|proposal\s+proyek)\b", 16),
            (r"\b(latar\s+belakang|rumusan\s+masalah|maksud\s+dan\s+tujuan)\b", 10),
            (r"\b(rancangan\s+anggaran|estimasi\s+biaya|jadwal\s+pelaksanaan)\b", 10),
            (r"\b(susunan\s+panitia|penutup)\b", 6),
        ],
    ),
    # certificate: achievement / completion certificate
    (
        "certificate",
        [
            (r"\b(sertifikat|piagam\s+penghargaan|certificate\s+of\s+completion)\b", 16),
            (r"\b(diberikan\s+kepada|awarded\s+to|this\s+is\s+to\s+certify)\b", 14),
            (r"\b(atas\s+partisipasinya|sebagai\s+peserta|sebagai\s+pembicara)\b", 10),
        ],
    ),
    # contract: legal contract / agreement
    (
        "contract",
        [
            (r"\b(surat\s+perjanjian|perjanjian\s+kerjasama|perjanjian\s+sewa|mou)\b", 16),
            (r"\b(pihak\s+pertama|pihak\s+kedua)\b", 12),
            (r"\b(pasal\s+\d+|syarat\s+dan\s+ketentuan)\b", 10),
            (r"\b(tanda\s+tangan\s+para\s+pihak|bermaterai)\b", 8),
        ],
    ),
    # report: formal report
    (
        "report",
        [
            (r"\b(laporan\s+pertanggungjawaban|lpj|laporan\s+tahunan|annual\s+report)\b", 16),
            (r"\b(executive\s+summary|ringkasan\s+eksekutif)\b", 10),
            (r"\b(bab\s+i|bab\s+ii|pendahuluan|kesimpulan)\b", 8),
        ],
    ),
    # form: registration / application form
    (
        "form",
        [
            (r"\b(formulir\s+pendaftaran|formulir\s+aplikasi|application\s+form)\b", 16),
            (r"\b(nama\s+lengkap|tempat[,\s/]+tanggal\s+lahir|jenis\s+kelamin)\b", 10),
            (r"\b(tanda\s+tangan\s+pemohon|signature)\b", 8),
        ],
    ),
]


def extract_document_number(text: str) -> str | None:
    """Extract official letter, invoice, or legal document registration number."""
    patterns = [
        # Invoice number: "Invoice Number: INV-2026-001" or "Invoice No: #12345"
        r"\b(?:invoice\s+(?:number|no\.?)|inv\s*#)[:\s]+([0-9A-Za-z\-./_#]{3,35})\b",
        # Generic invoice: "Invoice: #12345"
        r"\b(?:invoice)[:\s]+([0-9A-Za-z\-./_#]{3,35})\b",
        # Indonesian formal letter: "Nomor: 045/SK/DIR/IX/2026" or "No. : 123/ABC"
        r"\b(?:nomor|no\.?|nomor\s+surat)[:\s]+([0-9A-Za-z\-./_]{3,35})\b",
        # Reference number: "Ref: 9876/XYZ"
        r"\b(?:ref|reference)[:\s]+([0-9A-Za-z\-./_]{3,35})\b",
    ]
    for line in text.split("\n"):
        clean_line = line.strip()
        for pat in patterns:
            m = re.search(pat, clean_line, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                # Guard against common words matching
                if val.lower() not in ("surat", "lampiran", "perihal", "invoice", "date", "tanggal", "number"):
                    return val
    return None


def extract_subject(text: str) -> str | None:
    """Extract letter subject (Perihal / Hal / Subject)."""
    pat = r"^(?:perihal|hal|subject)[:\s]+(.+)$"
    for line in text.split("\n"):
        m = re.match(pat, line.strip(), re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_attachment(text: str) -> str | None:
    """Extract attachment detail (Lampiran / Attachment)."""
    pat = r"^(?:lampiran|lamp\.?|attachment)[:\s]+(.+)$"
    for line in text.split("\n"):
        m = re.match(pat, line.strip(), re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_recipient(text: str) -> str | None:
    """Extract recipient / addressee (Kepada Yth / Kepada / To / Bill To)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        clean = line.strip()
        m = re.match(r"^(?:kepada\s+yth\.?|kepada|to|bill\s+to)[:\s]*(.*)$", clean, re.IGNORECASE)
        if m:
            inline_val = m.group(1).strip()
            if inline_val:
                return inline_val
            # If line only contains "Kepada Yth.", take the immediate next line
            if i + 1 < len(lines):
                next_val = lines[i + 1].strip()
                if next_val and not next_val.startswith(("-", "=", ":")):
                    return next_val
    return None


def extract_sender(text: str) -> str | None:
    """Extract sender / creator (Dari / From / Pengirim)."""
    for line in text.split("\n"):
        clean = line.strip()
        m = re.match(r"^(?:dari|from|pengirim)[:\s]+(.+)$", clean, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_organization(lines: list[str]) -> str | None:
    """Extract issuing company, institution, or university from letterhead."""
    org_pattern = r"\b(?:pt\.?|cv\.?|universitas|institut|politeknik|kementerian|dinas|badan|pemerintah|yayasan)\s+([A-Za-z0-9\s&'\-]{2,40})"
    for line in lines[:6]:
        m = re.search(org_pattern, line.strip(), re.IGNORECASE)
        if m:
            return line.strip()
    return None


def extract_emails(text: str) -> list[str]:
    """Extract all emails in document."""
    return list(dict.fromkeys(m.group(0).lower() for m in re.finditer(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)))


def extract_phone_numbers(text: str) -> list[str]:
    """Extract Indonesian and standard international phone numbers."""
    phones: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:\+62\s?|0)8[1-9][0-9\-\s]{7,12}\b", text):
        clean = re.sub(r"[\-\s]", "", m.group(0))
        if 10 <= len(clean) <= 15 and clean not in seen:
            seen.add(clean)
            phones.append(clean)
    return phones


def parse_document_data(text: str) -> tuple[DocumentData, list[str]]:
    """Parse structured document details and determine document category."""
    warnings: list[str] = []
    cleaned = clean_document_text(text)
    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]

    # 1. Evaluate document type scoring
    scores: dict[str, int] = {}
    lower_text = cleaned.lower()

    for doc_type, rules in DOCUMENT_TYPE_RULES:
        t_score = 0
        for pattern, weight in rules:
            if re.search(pattern, lower_text):
                t_score += weight
        if t_score > 0:
            scores[doc_type] = t_score

    # Determine top document type
    top_type = "unknown"
    top_score = 0
    if scores:
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_type, top_score = sorted_types[0]

    # 2. Extract fields
    doc_number = extract_document_number(cleaned)
    date = extract_labeled_date(cleaned)
    subject = extract_subject(cleaned)
    attachment = extract_attachment(cleaned)
    recipient = extract_recipient(cleaned)
    sender = extract_sender(cleaned)
    organization = extract_organization(lines)
    all_dates = extract_document_dates(cleaned)
    amounts = extract_all_standalone_amounts(cleaned)
    emails = extract_emails(cleaned)
    phones = extract_phone_numbers(cleaned)

    # 3. Confidence computation
    confidence = 0.0
    if top_score >= 20:
        confidence = min(0.95, round(top_score / 32.0, 2))
    elif top_score >= 10:
        confidence = round(top_score / 32.0, 2)
    elif top_score > 0:
        confidence = 0.35
    else:
        confidence = 0.0

    # Boost confidence if key fields found
    if doc_number:
        confidence = min(0.98, confidence + 0.10)
    if subject:
        confidence = min(0.98, confidence + 0.08)

    # Ambiguity: If single isolated "Nomor 12345" without any other document features
    if top_score == 0 and doc_number:
        top_type = "unknown"
        confidence = 0.30

    doc_obj = DocumentData(
        document_type=top_type,
        document_number=doc_number,
        date=date,
        subject=subject,
        sender=sender,
        recipient=recipient,
        organization=organization,
        attachment=attachment,
        names=[],
        reference_numbers=[doc_number] if doc_number else [],
        important_dates=all_dates,
        important_amounts=amounts,
        emails=emails,
        phone_numbers=phones,
        confidence=confidence,
    )

    return doc_obj, warnings
