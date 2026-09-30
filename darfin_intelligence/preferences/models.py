"""Data models for user classification preferences (Task 2D)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UserPreference:
    """Represents a learned user association between a pattern and a target folder."""
    user_id: int
    pattern: str
    target_folder_id: int
    domain: str | None = None
    category: str | None = None
    positive_count: int = 1
    negative_count: int = 0
    confidence: float = 0.50
    is_stale: bool = False
    id: int | str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def calculate_boost(self) -> int:
        """Calculate score boost based on preference confidence and sample count."""
        # Minimum requirement: net positive choices
        if self.positive_count <= self.negative_count:
            return 0

        # Strong preference: 5+ consistent choices (confidence >= 0.85) -> +30
        if self.confidence >= 0.85:
            return 30
        # Medium preference: 3+ consistent choices (confidence >= 0.70) -> +20
        if self.confidence >= 0.70:
            return 20
        # Light preference: 1 choice (confidence >= 0.40) -> +10
        if self.confidence >= 0.40:
            return 10

        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "pattern": self.pattern,
            "target_folder_id": self.target_folder_id,
            "domain": self.domain,
            "category": self.category,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "confidence": round(self.confidence, 2),
            "is_stale": self.is_stale,
            "boost": self.calculate_boost(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class PreferenceBoost:
    """Applied score boost on a specific folder candidate."""
    folder_id: int
    pattern: str
    boost: int
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
