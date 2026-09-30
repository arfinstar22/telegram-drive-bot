"""Data models for domain and category classification results."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Candidate:
    """Scored candidate domain."""
    domain: str
    score: int
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ClassificationResult:
    """Output result of domain and category classification."""
    domain: str | None = None
    category: str | None = None
    status: str = "classified"  # "classified", "ambiguous", "unknown", "failed"
    confidence: float = 0.0
    scores: dict[str, int] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    top_candidates: list[dict[str, Any]] = field(default_factory=list)

    file_id: int | None = None
    filename: str = ""
    family: str = "other"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "domain": self.domain,
            "category": self.category,
            "status": self.status,
            "confidence": self.confidence,
            "scores": self.scores,
            "evidence": self.evidence,
            "top_candidates": self.top_candidates,
            "file_id": self.file_id,
            "filename": self.filename,
            "family": self.family,
        }
        if self.error:
            d["error"] = self.error
        return d

    def explain(self) -> str:
        """Produce human-readable explanation of the classification decision."""
        lines = [
            f"File: {self.filename}",
            f"Family: {self.family}",
            f"Decision: domain={self.domain or 'None'}, category={self.category or 'None'} (status={self.status}, confidence={self.confidence:.2f})",
            "",
            "Candidate scores:",
        ]
        for item in self.top_candidates:
            lines.append(f"  - {item['domain']}: {item['score']} (cat: {item.get('category', 'unknown')})")

        if self.evidence:
            lines.append("")
            lines.append("Evidence breakdown:")
            for ev in self.evidence:
                lines.append(f"  • {ev}")

        return "\n".join(lines)
