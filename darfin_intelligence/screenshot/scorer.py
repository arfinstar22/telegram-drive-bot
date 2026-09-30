"""Multi-signal scoring and classification engine for Screenshot Intelligence (Task 3B).

Evaluates extracted entities, keyword patterns, and structural cues to categorize screenshots.
Enforces:
- Multi-signal requirements (single keyword never gives high confidence)
- Ambiguity preservation when scores are close (e.g. 'Promo besok')
- OCR quality dampening when OCR confidence is low
- Privacy protection (never logs OTP or raw card numbers)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from darfin_intelligence.screenshot.models import (
    ExtractedEntities,
    SignalMatch,
)

log = logging.getLogger(__name__)

# All recognized screenshot categories
SCREENSHOT_CATEGORIES: frozenset[str] = frozenset({
    "conversation",
    "reminder",
    "receipt_candidate",
    "shopping",
    "education",
    "finance_candidate",
    "social_media",
    "webpage",
    "code",
    "document",
    "notification",
    "contact",
    "screenshot_unknown",
})

# Keyword signal tables with weights and strength levels
SIGNALS_TABLE: dict[str, list[tuple[str, int, str, str]]] = {
    # Category: [(keyword_regex, weight, strength, human_label)]
    "reminder": [
        (r"\b(rapat|meeting)\b", 8, "moderate", "event 'rapat/meeting'"),
        (r"\b(jadwal|agenda)\b", 6, "moderate", "schedule 'jadwal/agenda'"),
        (r"\b(jangan\s+lupa|reminder|pengingat)\b", 8, "moderate", "reminder phrase"),
        (r"\b(deadline|tenggat\s+waktu)\b", 8, "moderate", "deadline"),
        (r"\b(janjian|temu)\b", 6, "weak", "appointment 'janjian'"),
        (r"\b(webinar|zoom|gmeet)\b", 6, "moderate", "online meeting"),
    ],
    "receipt_candidate": [
        (r"\b(total|subtotal|grand\s+total)\b", 10, "strong", "total payment line"),
        (r"\b(kasir|cashier)\b", 8, "moderate", "cashier marker"),
        (r"\b(struk|nota|receipt)\b", 8, "moderate", "receipt marker"),
        (r"\b(kembalian|change|kembali)\b", 8, "moderate", "change/kembalian"),
        (r"\b(tunai|cash|qris)\b", 6, "moderate", "payment method"),
        (r"\b(qty|jumlah|harga|item|pcs)\b", 6, "moderate", "line items"),
        (r"\b(ppn|pajak|tax)\b", 6, "moderate", "tax marker"),
    ],
    "shopping": [
        (r"\b(checkout|check\s+out)\b", 12, "strong", "checkout action"),
        (r"\b(keranjang|troli|cart)\b", 8, "moderate", "shopping cart"),
        (r"\b(pesanan|order)\b", 6, "moderate", "order status"),
        (r"\b(ongkir|shipping|gratis\s+ongkir)\b", 8, "moderate", "shipping/ongkir"),
        (r"\b(promo|diskon|discount|sale)\b", 6, "moderate", "discount/promo"),
        (r"\b(voucher|cashback)\b", 6, "moderate", "voucher"),
        (r"\b(beli\s+sekarang|buy\s+now)\b", 10, "strong", "buy now action"),
    ],
    "education": [
        (r"\b(krs|khs|kartu\s+rencana\s+studi)\b", 14, "strong", "KRS/KHS document"),
        (r"\b(semester)\b", 8, "moderate", "semester"),
        (r"\b(mata\s+kuliah|matkul|sks)\b", 10, "strong", "course/credits"),
        (r"\b(npm|nim|nisn)\b", 10, "strong", "student ID number"),
        (r"\b(dosen|dosen\s+pembimbing)\b", 8, "moderate", "lecturer"),
        (r"\b(ujian|uts|uas)\b", 8, "moderate", "exam"),
        (r"\b(universitas|fakultas|prodi|mahasiswa)\b", 6, "moderate", "academic entity"),
        (r"\b(tugas\s+kuliah|praktikum)\b", 8, "moderate", "assignment"),
    ],
    "code": [
        (r"\b(def\s+[a-zA-Z_][a-zA-Z0-9_]*|function\s+[a-zA-Z_][a-zA-Z0-9_]*|class\s+[a-zA-Z_][a-zA-Z0-9_]*)\b", 14, "strong", "function/class definition"),
        (r"\b(import\s+[a-zA-Z_][a-zA-Z0-9_.]*|from\s+[a-zA-Z_.]+\s+import)\b", 12, "strong", "import statement"),
        (r"\b(async\s+def|await\s+[a-zA-Z_][a-zA-Z0-9_]*)\b", 10, "strong", "async/await"),
        (r"\b(const\s+[a-zA-Z_][a-zA-Z0-9_]*|let\s+[a-zA-Z_][a-zA-Z0-9_]*|var\s+[a-zA-Z_][a-zA-Z0-9_]*)\b", 10, "strong", "JS variable declaration"),
        (r"\b(traceback\s*\(most\s+recent\s+call\s+last\)|syntaxerror:|typeerror:|valueerror:|exception:)", 18, "strong", "stack trace / error"),
        (r"\bfile\s+\"[^\"]+\",\s+line\s+\d+", 12, "strong", "traceback line"),
        (r"\b(select\s+.+\s+from\s+[a-zA-Z_]+)\b", 12, "strong", "SQL query"),
        (r"\b(console\.log|print\(|return\s+)\b", 8, "moderate", "code statement"),
    ],
    "social_media": [
        (r"\b(instagram|tiktok|twitter|x\.com|facebook|youtube|threads)\b", 12, "strong", "social platform"),
        (r"\b(followers|following|pengikut|mengikuti)\b", 10, "strong", "follower metrics"),
        (r"\b(likes|disukai|komentar|comments)\b", 8, "moderate", "likes/comments"),
        (r"\b(share|bagikan|reels|fyp|postingan)\b", 6, "moderate", "post/share"),
        (r"\b(subscribe|subscribers|berlangganan)\b", 8, "moderate", "channel subscriber"),
    ],
    "document": [
        (r"\b(nomor:|no\.:|lampiran:|perihal:)\b", 14, "strong", "official letter header"),
        (r"\b(kepada\s+yth|dengan\s+hormat)\b", 12, "strong", "formal salutation"),
        (r"\b(menimbang|mengingat|memutuskan)\b", 12, "strong", "legal/formal decree"),
        (r"\b(surat\s+keputusan|surat\s+tugas|perjanjian)\b", 10, "strong", "official document type"),
    ],
    "notification": [
        (r"\b(otp|kode\s+verifikasi|verification\s+code|one-time\s+password)\b", 16, "strong", "OTP / verification code"),
        (r"\b(security\s+alert|peringatan\s+keamanan|login\s+baru|new\s+login)\b", 12, "strong", "security notification"),
        (r"\b(pembayaran\s+berhasil|transfer\s+berhasil|payment\s+successful)\b", 10, "strong", "transaction alert"),
    ],
    "finance_candidate": [
        (r"\b(saldo|rekening|mutasi\s+rekening)\b", 10, "strong", "account balance/statement"),
        (r"\b(transfer\s+ke|nominal\s+transfer|rekening\s+tujuan)\b", 10, "strong", "transfer details"),
        (r"\b(bca|mandiri|bri|bni|gopay|ovo|dana)\b", 6, "moderate", "bank / e-wallet"),
    ],
}


def evaluate_screenshot_signals(
    text: str,
    entities: ExtractedEntities,
) -> tuple[dict[str, int], list[SignalMatch], list[str]]:
    """Evaluate keyword and structural signals across all categories."""
    scores: dict[str, int] = {c: 0 for c in SCREENSHOT_CATEGORIES}
    matches: list[SignalMatch] = []
    evidence_notes: list[str] = []

    lower_text = text.lower()

    # 1. Evaluate keyword signals from table
    for cat, rules in SIGNALS_TABLE.items():
        for pattern, weight, strength, label in rules:
            m = re.search(pattern, lower_text)
            if m:
                scores[cat] += weight
                matched_val = m.group(0)
                matches.append(
                    SignalMatch(
                        category=cat,
                        signal=label,
                        weight=weight,
                        strength=strength,
                        matched_text=matched_val,
                    )
                )

    # 2. Structural & Entity Evidence: Reminder Co-occurrence
    has_date = len(entities.dates) > 0
    has_time = len(entities.times) > 0

    if has_date:
        scores["reminder"] += 8
        matches.append(
            SignalMatch(
                category="reminder",
                signal="date expression",
                weight=8,
                strength="moderate",
                matched_text=entities.dates[0].raw,
            )
        )
        evidence_notes.append(f"Date detected: {entities.dates[0].raw}")

    if has_time:
        scores["reminder"] += 10
        matches.append(
            SignalMatch(
                category="reminder",
                signal="time expression",
                weight=10,
                strength="moderate",
                matched_text=entities.times[0],
            )
        )
        evidence_notes.append(f"Time detected: {entities.times[0]}")

    if has_date and has_time:
        # Strong reminder signal: Date + Time co-occurring
        scores["reminder"] += 10
        matches.append(
            SignalMatch(
                category="reminder",
                signal="date + time co-occurrence",
                weight=10,
                strength="strong",
                matched_text=f"{entities.dates[0].raw} {entities.times[0]}",
            )
        )
        evidence_notes.append(f"Date ({entities.dates[0].raw}) and Time ({entities.times[0]}) co-occurring")

    # 3. Structural & Entity Evidence: Receipt Candidate
    has_prices = len(entities.prices) > 0
    has_merchant = entities.merchant is not None

    if has_merchant:
        scores["receipt_candidate"] += 8
        matches.append(
            SignalMatch(
                category="receipt_candidate",
                signal=f"merchant '{entities.merchant}'",
                weight=8,
                strength="moderate",
                matched_text=entities.merchant,
            )
        )
        evidence_notes.append(f"Merchant identified: '{entities.merchant}'")

    if has_prices:
        scores["receipt_candidate"] += 6
        scores["shopping"] += 4
        evidence_notes.append(f"Prices detected: {', '.join(p.raw for p in entities.prices[:3])}")
        # If total keyword co-occurs with price, massive receipt signal
        if re.search(r"\b(total|subtotal)\b", lower_text):
            scores["receipt_candidate"] += 12
            matches.append(
                SignalMatch(
                    category="receipt_candidate",
                    signal="total + price co-occurrence",
                    weight=12,
                    strength="strong",
                    matched_text=f"TOTAL {entities.prices[0].raw}",
                )
            )

    # 4. Structural Evidence: Conversation / Chat
    if len(entities.names) >= 2:
        # Multi-speaker chat dialogue
        scores["conversation"] += 20
        matches.append(
            SignalMatch(
                category="conversation",
                signal=f"multi-speaker dialog ({', '.join(entities.names[:3])})",
                weight=20,
                strength="strong",
                matched_text=f"{entities.names[0]} vs {entities.names[1]}",
            )
        )
        evidence_notes.append(f"Chat speakers detected: {', '.join(entities.names[:3])}")
    elif len(entities.names) == 1:
        scores["conversation"] += 8

    # 5. Structural Evidence: Webpage
    if len(entities.urls) > 0:
        scores["webpage"] += 12
        # If URL is github/gitlab, code score also boosted
        if any("github.com" in u.lower() or "gitlab.com" in u.lower() for u in entities.urls):
            scores["code"] += 8
        evidence_notes.append(f"URL detected: {entities.urls[0]}")

    # 6. Structural Evidence: Contact Card
    if len(entities.phone_numbers) > 0 and len(entities.emails) > 0:
        scores["contact"] += 16
        evidence_notes.append("Phone number and Email co-occurring")
    elif len(entities.phone_numbers) > 0:
        scores["contact"] += 6
        evidence_notes.append(f"Phone number: {entities.phone_numbers[0]}")

    # 7. Structural Evidence: Notification / OTP
    if len(entities.codes) > 0:
        scores["notification"] += 18
        matches.append(
            SignalMatch(
                category="notification",
                signal="verification code / OTP",
                weight=18,
                strength="strong",
                matched_text="[MASKED_OTP]",
            )
        )
        # PRIVACY RULE: Log that an OTP was found, but NEVER the value!
        evidence_notes.append("Security OTP / verification code detected")

    return scores, matches, evidence_notes


def classify_screenshot(
    scores: dict[str, int],
    matches: list[SignalMatch],
    evidence_notes: list[str],
    entities: ExtractedEntities,
    ocr_confidence: float | None = None,
) -> tuple[str, str, float, list[str]]:
    """Determine top category, status, confidence, and human explanation."""
    # Filter non-zero scores and sort descending
    scored = [(cat, sc) for cat, sc in scores.items() if sc > 0 and cat != "screenshot_unknown"]
    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored or scored[0][1] < 6:
        return (
            "screenshot_unknown",
            "unknown",
            0.0,
            ["Insufficient screenshot signals detected to determine category"],
        )

    top_cat, top_score = scored[0]

    # Evaluate Ambiguity (Section 23, 24, 45)
    # If second candidate is very close in score (diff <= 4 or ratio < 1.35)
    is_ambiguous = False
    if len(scored) >= 2:
        second_cat, second_score = scored[1]
        diff = top_score - second_score
        ratio = top_score / max(1, second_score)

        if diff <= 4 or (diff <= 6 and ratio < 1.35):
            is_ambiguous = True

    # Compute base classification confidence
    # Score 8 -> ~0.45, Score 20 -> ~0.75, Score 35+ -> ~0.95
    base_conf = min(0.95, round(top_score / 36.0, 2))
    if base_conf < 0.40:
        base_conf = 0.40

    if is_ambiguous:
        final_category = top_cat
        status = "ambiguous"
        # Dampen confidence on ambiguous competition
        final_conf = round(base_conf * 0.65, 2)
    else:
        final_category = top_cat
        status = "classified"
        final_conf = base_conf

    # Section 25 & 46: OCR Quality Awareness Dampening
    # If OCR confidence is low (< 0.60), dampen the classification confidence
    if ocr_confidence is not None:
        if ocr_confidence < 0.60:
            dampener = max(0.40, ocr_confidence)
            final_conf = round(final_conf * dampener, 2)

    # Build human explanation (Section 22)
    explanation: list[str] = []
    cat_matches = [m for m in matches if m.category == final_category]

    if is_ambiguous:
        explanation.append(
            f"Ambiguous category: closely competing '{top_cat}' ({top_score}) vs '{scored[1][0]}' ({scored[1][1]})"
        )
    else:
        explanation.append(f"Category identified as '{final_category}' (score: {top_score})")

    for m in cat_matches[:4]:
        explanation.append(f"✓ {m.signal} ({m.strength}, +{m.weight})")

    for ev in evidence_notes[:3]:
        explanation.append(f"• {ev}")

    return final_category, status, final_conf, explanation
