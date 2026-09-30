"""Data models for Task 3B Screenshot Intelligence Core."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ExtractedDate:
    """Represents an extracted relative or absolute date."""
    type: str  # "relative" | "absolute"
    value: str  # "today", "tomorrow", "day_after_tomorrow", or "YYYY-MM-DD"
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedPrice:
    """Represents an extracted price with currency and integer/float amount."""
    currency: str  # "IDR", "USD", etc.
    amount: int | float
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedEntities:
    """Structured collection of entities extracted from OCR text."""
    dates: list[ExtractedDate] = field(default_factory=list)
    times: list[str] = field(default_factory=list)
    prices: list[ExtractedPrice] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phone_numbers: list[str] = field(default_factory=list)
    merchant: str | None = None
    names: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    payment_sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dates": [d.to_dict() for d in self.dates],
            "times": self.times,
            "prices": [p.to_dict() for p in self.prices],
            "urls": self.urls,
            "emails": self.emails,
            "phone_numbers": self.phone_numbers,
            "merchant": self.merchant,
            "names": self.names,
            "codes": self.codes,
            "payment_sensitive": self.payment_sensitive,
        }


@dataclass
class SignalMatch:
    """Evidence signal matching a specific category."""
    category: str
    signal: str
    weight: int
    strength: str  # "strong" | "moderate" | "weak"
    matched_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenshotIntelligenceResult:
    """Structured result of screenshot content analysis and categorization."""
    status: str  # "classified" | "ambiguous" | "unknown"
    category: str  # One of SCREENSHOT_CATEGORIES
    confidence: float  # 0.0 to 1.0 (classification confidence)
    entities: ExtractedEntities = field(default_factory=ExtractedEntities)
    signals: list[SignalMatch] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    raw_text: str = ""
    normalized_text: str = ""
    ocr_confidence: float | None = None
    category_scores: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "entities": self.entities.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
            "evidence": self.evidence,
            "explanation": self.explanation,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "ocr_confidence": round(self.ocr_confidence, 4) if self.ocr_confidence is not None else None,
            "category_scores": self.category_scores,
        }
