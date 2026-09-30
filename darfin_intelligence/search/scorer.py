"""Transparent evidence-based scoring engine for Darfin Search Intelligence Core.

Combines exact, token, metadata, domain, OCR, entity, and fuzzy signals with explainability.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from darfin_intelligence.dictionaries import DOMAIN_KEYWORDS
from darfin_intelligence.search.fuzzy import fuzzy_match_token
from darfin_intelligence.search.index import IndexableFile
from darfin_intelligence.search.models import SearchMatch, SearchQuery
from darfin_intelligence.search.normalizer import canonical_alias


def calculate_recency_bonus(created_at_str: str) -> float:
    """Calculate small deterministic recency bonus (max +4.0)."""
    if not created_at_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff_days = (now - dt).days
        if diff_days <= 7:
            return 4.0
        elif diff_days <= 30:
            return 2.0
        elif diff_days <= 90:
            return 1.0
        return 0.0
    except (ValueError, TypeError):
        return 0.0


def score_file(
    file: IndexableFile,
    query: SearchQuery,
    preferences: dict[str, Any] | None = None,
) -> SearchMatch | None:
    """Evaluate and score an IndexableFile against a SearchQuery.

    Returns:
        SearchMatch with score, matched_fields, highlights, reasons, or None if no relevance.
    """
    score = 0.0
    matched_fields: list[str] = []
    reasons: list[str] = []
    highlights: dict[str, str] = {}
    matched_query_tokens: set[str] = set()

    raw_q_norm = query.normalized_query
    file_stem_norm = file.file_stem.lower()
    file_name_norm = file.file_name.lower()

    # Empty query case: return basic match for sorting
    if not query.tokens and not query.phrases and not query.entities:
        recency = calculate_recency_bonus(file.created_at)
        return SearchMatch(
            asset_id=file.asset_id,
            score=1.0 + recency,
            matched_fields=["all"],
            highlights={"file_name": file.file_name},
            reasons=["default match for empty query"],
            confidence=0.5,
            file_data=file.raw_item,
        )

    # 1. Exact Filename Match (+100)
    if raw_q_norm and (raw_q_norm == file_stem_norm or raw_q_norm == file_name_norm):
        score += 100.0
        matched_fields.append("file_name_exact")
        reasons.append(f"exact filename: {file.file_name}")
        highlights["file_name"] = file.file_name
        matched_query_tokens.update(query.tokens)
    elif len(query.tokens) > 1 and raw_q_norm and len(raw_q_norm) >= 3 and raw_q_norm in file_stem_norm:
        score += 65.0
        matched_fields.append("file_name_substring")
        reasons.append(f"full query substring in filename: {raw_q_norm}")
        highlights["file_name"] = file.file_name
        matched_query_tokens.update(query.tokens)

    # 2. Phrase Matching (+60 / +40 / +25)
    for phrase in query.phrases:
        if phrase in file_name_norm:
            score += 60.0
            matched_fields.append("phrase_match")
            reasons.append(f"phrase in filename: {phrase}")
            highlights["phrase"] = phrase
        elif phrase in file.folder_path.lower():
            score += 40.0
            matched_fields.append("folder_path")
            reasons.append(f"phrase in folder: {phrase}")
        elif file.ocr_text and phrase in file.ocr_text.lower():
            score += 25.0
            matched_fields.append("ocr_text")
            reasons.append(f"phrase in ocr text: {phrase}")

    # 3. Individual Query Tokens
    for tok in query.tokens:
        tok_canon = canonical_alias(tok)
        tok_matched_any = False

        # Category A: Filename matching
        if tok in file.filename_tokens or tok_canon in file.filename_tokens:
            score += 50.0
            matched_fields.append("file_name_token")
            reasons.append(f"filename token: {tok}")
            highlights["file_name"] = file.file_name
            tok_matched_any = True
        else:
            # Check punct-cleaned variant (e.g. web-dl vs web.dl)
            tok_clean = re.sub(r'[\s._\-]+', '', tok)
            file_clean = re.sub(r'[\s._\-]+', '', file_stem_norm)
            if len(tok_clean) >= 3 and tok_clean in file_clean:
                score += 45.0
                matched_fields.append("file_name_token")
                reasons.append(f"filename token variant: {tok}")
                highlights["file_name"] = file.file_name
                tok_matched_any = True
            elif len(tok) >= 3 and tok in file_stem_norm:
                score += 35.0
                matched_fields.append("file_name_substring")
                reasons.append(f"filename substring: {tok}")
                highlights["file_name"] = file.file_name
                tok_matched_any = True

        # Category B: Folder Name (+45) or Folder Path (+35)
        if file.folder_name:
            fn_lower = file.folder_name.lower()
            if tok == fn_lower or tok_canon == fn_lower:
                score += 45.0
                matched_fields.append("folder_name")
                reasons.append(f"folder name: {file.folder_name}")
                highlights["folder"] = file.folder_name
                tok_matched_any = True
            elif tok in fn_lower or (file.folder_path and tok in file.folder_path.lower()):
                score += 35.0
                matched_fields.append("folder_path")
                reasons.append(f"folder path: {file.folder_path or file.folder_name}")
                tok_matched_any = True

        # Category C: Tags (+40) & Notes (+25)
        if tok in file.tags or tok_canon in file.tags:
            score += 40.0
            matched_fields.append("tag")
            reasons.append(f"tag: {tok}")
            tok_matched_any = True
        if file.note and tok in file.note.lower():
            score += 25.0
            matched_fields.append("note")
            reasons.append(f"note: {tok}")
            highlights["note"] = file.note[:40]
            tok_matched_any = True

        # Category D: Domain (+35)
        domain_match = False
        if file.domain and (tok == file.domain or tok_canon == file.domain):
            domain_match = True
        elif file.domain and tok in DOMAIN_KEYWORDS.get(file.domain, []):
            domain_match = True
        if domain_match:
            score += 35.0
            matched_fields.append("domain")
            reasons.append(f"domain context: {file.domain}")
            tok_matched_any = True

        # Category E: Extension (+30) / Family (+30)
        if tok == file.extension or tok_canon == file.extension:
            score += 30.0
            matched_fields.append("extension")
            reasons.append(f"extension match: {file.extension}")
            tok_matched_any = True
        if tok == file.family or tok_canon == file.family:
            score += 30.0
            matched_fields.append("family")
            reasons.append(f"file family: {file.family}")
            tok_matched_any = True

        # Category F: Task 3C Structured Fields (+40)
        if file.merchant_name and tok in file.merchant_name.lower():
            score += 40.0
            matched_fields.append("merchant_name")
            reasons.append(f"merchant: {file.merchant_name}")
            highlights["merchant"] = file.merchant_name
            tok_matched_any = True
        if file.receipt_number and tok in file.receipt_number.lower():
            score += 40.0
            matched_fields.append("receipt_number")
            reasons.append(f"receipt no: {file.receipt_number}")
            tok_matched_any = True
        if file.document_number and tok in file.document_number.lower():
            score += 40.0
            matched_fields.append("document_number")
            reasons.append(f"document no: {file.document_number}")
            tok_matched_any = True
        if file.subject and tok in file.subject.lower():
            score += 40.0
            matched_fields.append("subject")
            reasons.append(f"subject: {file.subject}")
            tok_matched_any = True
        if file.document_type and (tok == file.document_type or tok_canon == file.document_type):
            score += 35.0
            matched_fields.append("document_type")
            reasons.append(f"document type: {file.document_type}")
            tok_matched_any = True
        if file.payment_method and (tok == file.payment_method or tok_canon == file.payment_method):
            score += 30.0
            matched_fields.append("payment_method")
            reasons.append(f"payment method: {file.payment_method}")
            tok_matched_any = True

        # Category G: Task 3B Screenshot Category (+35)
        if file.screenshot_category and (tok == file.screenshot_category or tok_canon == file.screenshot_category):
            score += 35.0
            matched_fields.append("screenshot_category")
            reasons.append(f"screenshot category: {file.screenshot_category}")
            tok_matched_any = True

        # Category H: OCR Text Matching (+20 * conf)
        if file.ocr_text and tok in file.ocr_text.lower():
            ocr_mult = min(1.0, max(0.4, file.ocr_confidence)) if file.ocr_confidence > 0 else 0.8
            ocr_pts = 20.0 * ocr_mult
            score += ocr_pts
            matched_fields.append("ocr_text")
            reasons.append(f"ocr text: '{tok}' (conf: {ocr_mult:.2f})")
            idx = file.ocr_text.lower().find(tok)
            start = max(0, idx - 15)
            end = min(len(file.ocr_text), idx + len(tok) + 15)
            highlights["ocr_snippet"] = "..." + file.ocr_text[start:end].strip() + "..."
            tok_matched_any = True

        # If any exact/metadata category matched, record token coverage and skip fuzzy
        if tok_matched_any:
            matched_query_tokens.add(tok)
            continue

        # Category I: Deterministic Fuzzy Matching (+15 to +25)
        candidate_words = file.filename_tokens + ([file.folder_name] if file.folder_name else [])
        if file.merchant_name:
            candidate_words.append(file.merchant_name)
        ratio, matched_word = fuzzy_match_token(tok, candidate_words, threshold=0.80)
        if ratio >= 0.80 and matched_word:
            fuzz_pts = 15.0 + (ratio * 10.0)
            score += fuzz_pts
            matched_fields.append("fuzzy_match")
            reasons.append(f"fuzzy: '{tok}' ~ '{matched_word}' ({ratio:.2f})")
            matched_query_tokens.add(tok)
            continue

    # 4. Amount & Entity Matching
    if "amount" in query.entities and file.total_amount is not None:
        target_amt = float(query.entities["amount"])
        if abs(file.total_amount - target_amt) < 1.0:
            score += 45.0
            matched_fields.append("total_amount")
            reasons.append(f"total amount match: {int(target_amt)}")
            highlights["amount"] = f"Total: {int(target_amt)}"

    if "year" in query.entities and query.entities["year"] in file.created_at:
        score += 15.0
        matched_fields.append("year")
        reasons.append(f"created year: {query.entities['year']}")

    # 5. Multi-Token Coverage Bonus
    if len(query.tokens) > 1 and len(matched_query_tokens) == len(query.tokens):
        score += 25.0
        reasons.append("full token coverage bonus")
    elif len(query.tokens) > 2 and len(matched_query_tokens) >= len(query.tokens) * 0.7:
        score += 15.0
        reasons.append("high token coverage bonus")

    # 6. Recency Bonus (+1 to +4)
    recency = calculate_recency_bonus(file.created_at)
    if recency > 0:
        score += recency
        reasons.append(f"recency bonus: +{recency:.1f}")

    # 7. User Preference Bonus (+8)
    if preferences and isinstance(preferences, dict):
        if file.folder_id and str(file.folder_id) in preferences.get("preferred_folders", []):
            score += 8.0
            reasons.append("user preferred folder bonus")
        elif file.domain and file.domain in preferences.get("preferred_domains", []):
            score += 8.0
            reasons.append("user preferred domain bonus")

    # 8. Conflict Penalty (-30)
    # If query specified video/movie but file is document/audio
    if any(tok in ("video", "film", "movie") for tok in query.tokens) and file.family not in ("video", "media"):
        score -= 30.0
        reasons.append("conflict penalty: query wanted video, file is not video")
    elif any(tok in ("pdf", "document", "dokumen") for tok in query.tokens) and file.family not in ("document", "office"):
        score -= 30.0
        reasons.append("conflict penalty: query wanted document, file is not document")

    # Final threshold check
    if score <= 0.0 or not matched_fields:
        return None

    # Confidence calculation: 150.0 is reference score for multi-signal high confidence
    confidence = min(1.0, max(0.1, score / 150.0))

    # Single weak fuzzy match dampens confidence
    if len(matched_fields) == 1 and matched_fields[0] == "fuzzy_match":
        confidence = min(0.35, confidence)

    # Unique fields list preserving order
    unique_fields: list[str] = []
    for f_name in matched_fields:
        if f_name not in unique_fields:
            unique_fields.append(f_name)

    return SearchMatch(
        asset_id=file.asset_id,
        score=score,
        matched_fields=unique_fields,
        highlights=highlights,
        reasons=reasons,
        confidence=confidence,
        file_data=file.raw_item,
    )
