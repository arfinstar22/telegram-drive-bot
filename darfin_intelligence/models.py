"""Data models for intelligence results.

All fields nullable by design — NULL beats guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class FileTypeInfo:
    """Detected file type information."""
    family: str = "other"  # video, image, audio, document, archive, other
    extension: str | None = None
    extension_normalized: str | None = None
    mime_type: str | None = None
    mime_family: str | None = None  # video, image, audio, document, archive
    container: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MediaEntities:
    """Extracted entities from media-style filenames."""
    title: str | None = None
    year: int | None = None
    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    audio_codec: str | None = None
    language: str | None = None
    season: int | None = None
    episode: int | None = None
    release_group: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Signal:
    """Single evidence signal."""
    source: str  # mime, extension, technical_marker, domain_keyword, structural
    category: str  # video, image, audio, document, archive, education, office, finance, media
    value: str  # the actual token/value that triggered this signal
    weight: int  # numeric weight
    level: int  # 1-5 hierarchy level

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IntelligenceResult:
    """Complete analysis result for a single file."""
    file_id: int | None = None
    filename_original: str = ""
    filename_normalized: str = ""
    tokens: list[str] = field(default_factory=list)

    file_type: FileTypeInfo = field(default_factory=FileTypeInfo)
    entities: MediaEntities = field(default_factory=MediaEntities)

    signals: list[Signal] = field(default_factory=list)
    signal_scores: dict[str, int] = field(default_factory=dict)

    confidence: dict[str, float] = field(default_factory=dict)

    domain_signals: dict[str, str] = field(default_factory=dict)

    parser_name: str = "generic"
    parser_version: str = "1.0.0"
    status: str = "success"  # success, partial, failed
    error: str | None = None

    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "file_id": self.file_id,
            "filename_original": self.filename_original,
            "filename_normalized": self.filename_normalized,
            "tokens": self.tokens,
            "file_type": self.file_type.to_dict(),
            "entities": self.entities.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
            "signal_scores": self.signal_scores,
            "confidence": self.confidence,
            "domain_signals": self.domain_signals,
            "parser": {
                "name": self.parser_name,
                "version": self.parser_version,
            },
            "status": self.status,
            "evidence": self.evidence,
        }
        if self.error:
            d["error"] = self.error
        return d

    def explain(self) -> str:
        """Human-readable explanation of how the result was determined."""
        lines = [
            f"File: {self.filename_original}",
            f"Detected family: {self.file_type.family}",
            f"Parser: {self.parser_name} v{self.parser_version}",
            "",
            "Evidence chain:",
        ]
        for sig in sorted(self.signals, key=lambda s: -s.weight):
            lines.append(f"  [{sig.source}] {sig.category}={sig.value} (weight={sig.weight}, level={sig.level})")
        lines.append("")
        lines.append("Score totals:")
        for cat, score in sorted(self.signal_scores.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {score}")
        if self.entities.to_dict():
            lines.append("")
            lines.append("Entities:")
            for k, v in self.entities.to_dict().items():
                lines.append(f"  {k}: {v}")
        if self.confidence:
            lines.append("")
            lines.append("Confidence:")
            for k, v in sorted(self.confidence.items(), key=lambda x: -x[1]):
                lines.append(f"  {k}: {v:.2f}")
        return "\n".join(lines)
