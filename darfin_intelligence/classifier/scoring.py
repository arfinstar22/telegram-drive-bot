"""Scoring engine and candidate classification logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from darfin_intelligence.classifier.models import Candidate, ClassificationResult
from darfin_intelligence.classifier.domain import (
    DOMAINS,
    WEIGHT_WEAK,
    get_token_weight,
    resolve_category,
)

if TYPE_CHECKING:
    from darfin_intelligence.models import IntelligenceResult


def compute_classification(result: IntelligenceResult) -> ClassificationResult:
    """Analyze an IntelligenceResult and classify into domain and category.

    Args:
        result: IntelligenceResult produced by Task 1.

    Returns:
        ClassificationResult with domain, category, status, confidence, and explanation.
    """
    family = result.file_type.family if result.file_type else "other"
    filename = result.filename_original
    file_id = result.file_id

    scores: dict[str, int] = {dom: 0 for dom in DOMAINS if dom != "unknown"}
    evidence: list[str] = []

    # 1. Score keyword tokens from filename
    tokens_lower = [t.lower() for t in result.tokens]
    for token in result.tokens:
        tok_lower = token.lower()
        for dom in scores.keys():
            w, strength = get_token_weight(dom, tok_lower)
            if w > 0:
                scores[dom] += w
                evidence.append(f"[{strength.upper()}] Keyword '{token}' matches {dom} (+{w})")

    # 2. Apply Family Compatibility Bonuses & Constraints
    if family == "video":
        # Video is overwhelmingly media
        media_bonus = 100
        # If technical markers exist (resolution, source, codec)
        if any(s.source == "technical_marker" for s in result.signals) or result.entities.resolution or result.entities.source:
            media_bonus += 30
        scores["media"] += media_bonus
        evidence.append(f"[FAMILY] Strong media container & technical markers (+{media_bonus})")

        # Heavy conflict penalty against non-media domains on video files
        for dom in ("office", "education", "finance", "legal", "health"):
            if scores[dom] > 0:
                penalized = max(0, scores[dom] - 50)
                evidence.append(f"[CONFLICT] Domain '{dom}' penalized due to video format ({scores[dom]} -> {penalized})")
                scores[dom] = penalized

    elif family == "document":
        # Document cannot easily be a movie/video media
        if scores["media"] > 0:
            evidence.append(f"[CONFLICT] Media domain penalized for document file ({scores['media']} -> 0)")
            scores["media"] = 0

        # Document format confirms document-aligned domains
        evidence.append("[FORMAT] Document format confirms document domains")

    elif family == "image":
        # Images can be photos, scans of documents, or screenshots
        if result.parser_name == "whatsapp_filename_parser":
            scores["personal"] += 20
            evidence.append("[FORMAT] WhatsApp image aligns with personal (+20)")
        if any(t in tokens_lower for t in ("screenshot", "tangkapan_layar")):
            scores["office"] += 5
            scores["project"] += 5
        # Scanned identity document
        if any(t in tokens_lower for t in ("ktp", "sim", "paspor", "npwp", "kk")):
            scores["identity"] += 25
            evidence.append("[FORMAT] Image scanned identity token detected (+25)")

    elif family == "audio":
        if result.parser_name == "whatsapp_filename_parser" or "voice" in tokens_lower or "ptt" in tokens_lower:
            scores["personal"] += 30
            evidence.append("[FORMAT] WhatsApp voice audio aligns with personal (+30)")
        elif any(t in tokens_lower for t in ("kuliah", "lecture", "seminar")):
            scores["education"] += 20
        else:
            scores["media"] += 20
            evidence.append("[FORMAT] Audio aligns with media/music (+20)")

    elif family == "archive":
        if any(t in tokens_lower for t in ("backup", "bak")):
            scores["personal"] += 20
            scores["office"] += 10
        elif any(t in tokens_lower for t in ("project", "proyek", "src", "code", "repo")):
            scores["project"] += 25
            evidence.append("[FORMAT] Archive contains project/code tokens (+25)")

    # 3. Candidate Ranking
    candidates: list[Candidate] = []
    for dom, sc in scores.items():
        if sc > 0:
            candidates.append(Candidate(domain=dom, score=sc))

    candidates.sort(key=lambda c: -c.score)

    # 4. Fallback if no positive scores
    if not candidates:
        if family == "video":
            cat = resolve_category(result, "media")
            return ClassificationResult(
                domain="media",
                category=cat,
                status="classified",
                confidence=0.90,
                scores=scores,
                evidence=evidence + ["[DEFAULT] Video file defaulted to media"],
                top_candidates=[{"domain": "media", "score": 100, "category": cat}],
                file_id=file_id,
                filename=filename,
                family=family,
            )
        if family == "image":
            cat = resolve_category(result, "personal")
            return ClassificationResult(
                domain="personal",
                category=cat,
                status="classified",
                confidence=0.70,
                scores=scores,
                evidence=evidence + ["[DEFAULT] Image defaulted to personal photo"],
                top_candidates=[{"domain": "personal", "score": 15, "category": cat}],
                file_id=file_id,
                filename=filename,
                family=family,
            )
        if family == "audio":
            cat = resolve_category(result, "media")
            return ClassificationResult(
                domain="media",
                category=cat,
                status="classified",
                confidence=0.70,
                scores=scores,
                evidence=evidence + ["[DEFAULT] Audio defaulted to media"],
                top_candidates=[{"domain": "media", "score": 20, "category": cat}],
                file_id=file_id,
                filename=filename,
                family=family,
            )
        if family == "archive":
            cat = resolve_category(result, "project")
            return ClassificationResult(
                domain="project",
                category=cat,
                status="classified",
                confidence=0.60,
                scores=scores,
                evidence=evidence + ["[DEFAULT] Archive defaulted to project"],
                top_candidates=[{"domain": "project", "score": 10, "category": cat}],
                file_id=file_id,
                filename=filename,
                family=family,
            )

        # Unidentifiable document or other
        return ClassificationResult(
            domain=None,
            category="unknown_document" if family == "document" else "unknown",
            status="unknown",
            confidence=0.0,
            scores=scores,
            evidence=evidence + ["[INSUFFICIENT] No identifiable domain keywords or signals"],
            top_candidates=[],
            file_id=file_id,
            filename=filename,
            family=family,
        )

    # 5. Calculate Confidence & Check Ambiguity
    total_pos_score = sum(c.score for c in candidates)
    top = candidates[0]
    confidence = round(top.score / total_pos_score, 4) if total_pos_score > 0 else 0.0

    # Populate categories in candidate list
    candidate_dicts: list[dict[str, Any]] = []
    for c in candidates:
        cat = resolve_category(result, c.domain)
        c.category = cat
        candidate_dicts.append(c.to_dict())

    # Ambiguity check:
    # If 2 or more candidates have very close scores and neither is dominant
    if len(candidates) >= 2:
        second = candidates[1]
        diff = top.score - second.score
        ratio = top.score / max(1, second.score)

        # Ambiguous if tied or separated by <= 2 points with low ratio
        if diff == 0 or (diff <= 2 and ratio < 1.35):
            evidence.append(
                f"[AMBIGUITY] Top candidates {top.domain} ({top.score}) and {second.domain} ({second.score}) too close"
            )
            return ClassificationResult(
                domain=None,
                category=None,
                status="ambiguous",
                confidence=round(confidence, 2),
                scores=scores,
                evidence=evidence,
                top_candidates=candidate_dicts[:5],
                file_id=file_id,
                filename=filename,
                family=family,
            )

    # For files with only 1 weak keyword (score <= 3), dampen confidence so it is not overly high
    if top.score <= WEIGHT_WEAK:
        confidence = min(confidence, 0.45)

    winning_domain = top.domain
    winning_category = resolve_category(result, winning_domain)
    top.category = winning_category

    return ClassificationResult(
        domain=winning_domain,
        category=winning_category,
        status="classified",
        confidence=round(confidence, 2),
        scores=scores,
        evidence=evidence,
        top_candidates=candidate_dicts[:5],
        file_id=file_id,
        filename=filename,
        family=family,
    )
