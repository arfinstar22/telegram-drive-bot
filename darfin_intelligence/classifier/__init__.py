"""Smart Domain Classifier package for Darfin Storage.

Consumes IntelligenceResult from Task 1 and outputs structured ClassificationResult
with domain, category, confidence, status, candidates, and explainability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from darfin_intelligence.classifier.models import ClassificationResult, Candidate
from darfin_intelligence.classifier.scoring import compute_classification

if TYPE_CHECKING:
    from darfin_intelligence.models import IntelligenceResult


def classify(result: IntelligenceResult) -> ClassificationResult:
    """Classify an IntelligenceResult into domain and category.

    Args:
        result: IntelligenceResult produced by darfin_intelligence.analyze()

    Returns:
        ClassificationResult with domain, category, status, confidence, and explain.
    """
    try:
        return compute_classification(result)
    except Exception as exc:
        return ClassificationResult(
            domain=None,
            category=None,
            status="failed",
            confidence=0.0,
            error=str(exc),
            file_id=getattr(result, "file_id", None),
            filename=getattr(result, "filename_original", ""),
            family=getattr(result.file_type, "family", "other") if getattr(result, "file_type", None) else "other",
        )


class DomainClassifier:
    """Class-based interface for the domain classifier."""

    @staticmethod
    def classify(result: IntelligenceResult) -> ClassificationResult:
        return classify(result)


__all__ = ["classify", "DomainClassifier", "ClassificationResult", "Candidate"]
