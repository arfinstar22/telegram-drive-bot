"""Data models for Task 3A Local OCR Core."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class OCRBlock:
    """Represents an extracted text block, paragraph, or line with bounding box and confidence."""
    text: str
    confidence: float  # 0.0 to 100.0
    line_num: int | None = None
    bbox: tuple[int, int, int, int] | None = None  # (left, top, width, height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OCRResult:
    """Structured output result of OCR processing."""
    status: str  # "success" | "failed" | "rejected" | "timeout" | "unsupported_format"
    raw_text: str = ""
    normalized_text: str = ""
    language: str = "eng"
    confidence: float | None = None  # 0.0 to 1.0 (OCR confidence, NEVER AI confidence)
    engine: str = "tesseract"
    engine_version: str | None = None
    processing_time_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    blocks: list[OCRBlock] = field(default_factory=list)
    image_hash: str | None = None
    dimensions: tuple[int, int] | None = None  # (width, height)
    file_size_bytes: int = 0

    @property
    def text(self) -> str:
        """Convenience property returning cleaned/normalized text."""
        return self.normalized_text or self.raw_text

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "text": self.text,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "language": self.language,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "processing_time_ms": self.processing_time_ms,
            "file_size_bytes": self.file_size_bytes,
        }
        if self.error_code:
            d["error_code"] = self.error_code
        if self.error_message:
            d["error_message"] = self.error_message
        if self.dimensions:
            d["dimensions"] = self.dimensions
        if self.image_hash:
            d["image_hash"] = self.image_hash
        if self.blocks:
            d["blocks"] = [b.to_dict() for b in self.blocks]
        return d
