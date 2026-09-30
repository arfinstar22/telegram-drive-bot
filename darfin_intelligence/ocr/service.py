"""OCR Service orchestrator for Local OCR Core (Task 3A).

Coordinates:
- Format verification (.jpg, .jpeg, .png, .webp)
- File size checking (rejects oversized images)
- Image dimension validation (protects against decompression bombs)
- Optional lightweight preprocessing (grayscale, contrast)
- Local engine delegation (LocalTesseractEngine / MockOCREngine)
- Text cleaning and normalization (clean_ocr_text)
- Safe, non-crashing execution (returns structured OCRResult)
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import time
from typing import Any

from darfin_intelligence.ocr.cleaner import clean_ocr_text
from darfin_intelligence.ocr.engine import BaseOCREngine, LocalTesseractEngine
from darfin_intelligence.ocr.models import OCRResult

log = logging.getLogger(__name__)

# Supported image file extensions
SUPPORTED_FORMATS: frozenset[str] = frozenset({"jpg", "jpeg", "png", "webp"})

# Default limits (can be configured via config.py or environment)
DEFAULT_MAX_FILE_SIZE_MB = 20
DEFAULT_MAX_DIMENSION = 10000
DEFAULT_MAX_PIXELS = 25000000  # 25 Megapixels
DEFAULT_TIMEOUT_SECONDS = 15


def _compute_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a local file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class LocalOCREngine:
    """Core local OCR service coordinating validation, execution, and text normalization."""

    def __init__(
        self,
        engine: BaseOCREngine | None = None,
        max_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        max_dimension: int = DEFAULT_MAX_DIMENSION,
        max_pixels: int = DEFAULT_MAX_PIXELS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        default_language: str = "eng",
    ) -> None:
        self.engine = engine or LocalTesseractEngine()
        self.max_size_mb = max_size_mb
        self.max_dimension = max_dimension
        self.max_pixels = max_pixels
        self.timeout_seconds = timeout_seconds
        self.default_language = default_language

    def is_available(self) -> bool:
        """Check if OCR is available in the current environment."""
        return self.engine.is_available()

    def process(
        self,
        image_path: str,
        language: str | None = None,
        preprocess: bool = False,
    ) -> OCRResult:
        """Execute OCR on a local image file.

        Guarantees:
        - Never raises unhandled exceptions to caller
        - Validates input format, size, and dimensions
        - Preserves raw output in raw_text, standardized text in normalized_text
        - Returns structured OCRResult with timing and confidence
        """
        start_time = time.perf_counter()
        lang = language or self.default_language

        # 1. Check file existence
        if not image_path or not os.path.isfile(image_path):
            return OCRResult(
                status="failed",
                error_code="INVALID_IMAGE",
                error_message="Image file does not exist or is not a readable file.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
            )

        # 2. Check supported extension
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        if ext not in SUPPORTED_FORMATS:
            return OCRResult(
                status="unsupported_format",
                error_code="UNSUPPORTED_FORMAT",
                error_message=f"File extension '.{ext}' is not supported. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
            )

        # 3. Check file size
        try:
            file_size_bytes = os.path.getsize(image_path)
        except OSError as e:
            return OCRResult(
                status="failed",
                error_code="INVALID_IMAGE",
                error_message=f"Cannot inspect file size: {e}",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
            )

        max_bytes = self.max_size_mb * 1024 * 1024
        if file_size_bytes > max_bytes:
            return OCRResult(
                status="rejected",
                error_code="OCR_IMAGE_TOO_LARGE",
                error_message=f"Image size ({file_size_bytes / (1024*1024):.2f} MB) exceeds maximum allowed ({self.max_size_mb} MB).",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
                file_size_bytes=file_size_bytes,
            )

        # 4. Check image dimensions and integrity (using Pillow if available)
        dimensions: tuple[int, int] | None = None
        try:
            from PIL import Image

            # Prevent DecompressionBomb denial-of-service
            Image.MAX_IMAGE_PIXELS = self.max_pixels

            with Image.open(image_path) as img:
                dimensions = (img.width, img.height)

                # Format verification
                img_fmt = (img.format or "").lower()
                fmt_normalized = "jpg" if img_fmt == "jpeg" else img_fmt
                if fmt_normalized not in SUPPORTED_FORMATS:
                    return OCRResult(
                        status="unsupported_format",
                        error_code="UNSUPPORTED_FORMAT",
                        error_message=f"Image internal format '{img_fmt}' is not supported.",
                        language=lang,
                        engine=self.engine.engine_name,
                        engine_version=self.engine.get_version(),
                        dimensions=dimensions,
                        file_size_bytes=file_size_bytes,
                    )

                # Dimension check
                if img.width > self.max_dimension or img.height > self.max_dimension:
                    return OCRResult(
                        status="rejected",
                        error_code="OCR_IMAGE_DIMENSIONS_TOO_LARGE",
                        error_message=f"Image dimensions ({img.width}x{img.height}) exceed maximum allowed dimension ({self.max_dimension}).",
                        language=lang,
                        engine=self.engine.engine_name,
                        engine_version=self.engine.get_version(),
                        dimensions=dimensions,
                        file_size_bytes=file_size_bytes,
                    )

                if (img.width * img.height) > self.max_pixels:
                    return OCRResult(
                        status="rejected",
                        error_code="OCR_IMAGE_DIMENSIONS_TOO_LARGE",
                        error_message=f"Image total pixels ({img.width * img.height}) exceed maximum allowed ({self.max_pixels}).",
                        language=lang,
                        engine=self.engine.engine_name,
                        engine_version=self.engine.get_version(),
                        dimensions=dimensions,
                        file_size_bytes=file_size_bytes,
                    )

                # Verify image integrity
                img.verify()
        except ImportError:
            # Pillow not available in environment; continue with basic extension check
            pass
        except Exception as exc:
            log.warning("Image verification failed for '%s': %s", image_path, exc)
            return OCRResult(
                status="failed",
                error_code="INVALID_IMAGE",
                error_message="Image file is corrupt, malformed, or invalid.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
                file_size_bytes=file_size_bytes,
            )

        # 5. Check engine availability
        if not self.engine.is_available():
            return OCRResult(
                status="failed",
                error_code="OCR_UNAVAILABLE",
                error_message="Local OCR engine is not installed or available in this environment.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=None,
                dimensions=dimensions,
                file_size_bytes=file_size_bytes,
            )

        # 6. Compute file hash for identification
        image_hash = _compute_sha256(image_path)

        # 7. Optional lightweight preprocessing
        effective_path = image_path
        temp_preprocessed_file: str | None = None
        if preprocess:
            try:
                from PIL import Image, ImageEnhance

                with Image.open(image_path) as img:
                    # Convert to grayscale
                    gray = img.convert("L")
                    # Mild contrast boost
                    enhancer = ImageEnhance.Contrast(gray)
                    enhanced = enhancer.enhance(1.4)

                    stem = os.path.splitext(os.path.basename(image_path))[0]
                    fd, tmp_path = tempfile.mkstemp(prefix=f"prep_{stem}_", suffix=".png")
                    os.close(fd)
                    enhanced.save(tmp_path, format="PNG")
                    effective_path = tmp_path
                    temp_preprocessed_file = tmp_path
            except Exception as prep_err:
                log.debug("Preprocessing skipped due to error: %s", prep_err)
                effective_path = image_path

        # 8. Execute engine
        try:
            raw_text, confidence, blocks = self.engine.extract(
                effective_path,
                language=lang,
                timeout_seconds=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.warning("OCR timed out after %ds for %s", self.timeout_seconds, image_path)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return OCRResult(
                status="timeout",
                error_code="OCR_TIMEOUT",
                error_message=f"OCR processing timed out after {self.timeout_seconds} seconds.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
                processing_time_ms=elapsed_ms,
                dimensions=dimensions,
                file_size_bytes=file_size_bytes,
                image_hash=image_hash,
            )
        except Exception as ocr_err:
            log.error("OCR execution error for %s: %s", image_path, ocr_err)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return OCRResult(
                status="failed",
                error_code="OCR_ENGINE_ERROR",
                error_message="Internal OCR engine error occurred during processing.",
                language=lang,
                engine=self.engine.engine_name,
                engine_version=self.engine.get_version(),
                processing_time_ms=elapsed_ms,
                dimensions=dimensions,
                file_size_bytes=file_size_bytes,
                image_hash=image_hash,
            )
        finally:
            if temp_preprocessed_file and os.path.exists(temp_preprocessed_file):
                try:
                    os.remove(temp_preprocessed_file)
                except OSError:
                    pass

        # 9. Clean and normalize text
        normalized_text = clean_ocr_text(raw_text)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        return OCRResult(
            status="success",
            raw_text=raw_text,
            normalized_text=normalized_text,
            language=lang,
            confidence=confidence,
            engine=self.engine.engine_name,
            engine_version=self.engine.get_version(),
            processing_time_ms=elapsed_ms,
            blocks=blocks,
            image_hash=image_hash,
            dimensions=dimensions,
            file_size_bytes=file_size_bytes,
        )


# Global default service instance
_default_ocr_service = LocalOCREngine()


def ocr_available() -> bool:
    """Check if local OCR engine is available."""
    return _default_ocr_service.is_available()


def ocr(
    image_path: str,
    language: str | None = None,
    preprocess: bool = False,
    engine: BaseOCREngine | None = None,
) -> OCRResult:
    """Extract text from local image file.

    Synchronous, deterministic, and safe (never raises unhandled exceptions).
    """
    service = _default_ocr_service if engine is None else LocalOCREngine(engine=engine)
    return service.process(image_path=image_path, language=language, preprocess=preprocess)


def extract_text(
    image_path: str,
    language: str | None = None,
    preprocess: bool = False,
    engine: BaseOCREngine | None = None,
) -> OCRResult:
    """Alias for ocr()."""
    return ocr(image_path=image_path, language=language, preprocess=preprocess, engine=engine)


def analyze_image_text(
    image_path: str,
    language: str | None = None,
    preprocess: bool = False,
) -> OCRResult:
    """Safe secondary integration hook for upload pipelines.

    Guarantees zero exceptions and fail-safe return.
    """
    try:
        return ocr(image_path=image_path, language=language, preprocess=preprocess)
    except Exception as exc:
        log.error("Unexpected error in analyze_image_text for %s: %s", image_path, exc)
        return OCRResult(
            status="failed",
            error_code="OCR_ENGINE_ERROR",
            error_message="Unexpected error during OCR analysis.",
        )


# OCRService facade class
class OCRService:
    """Facade for Local OCR capabilities."""

    @staticmethod
    def is_available() -> bool:
        return ocr_available()

    @staticmethod
    def ocr(
        image_path: str,
        language: str | None = None,
        preprocess: bool = False,
        engine: BaseOCREngine | None = None,
    ) -> OCRResult:
        return ocr(image_path, language=language, preprocess=preprocess, engine=engine)

    @staticmethod
    def extract_text(
        image_path: str,
        language: str | None = None,
        preprocess: bool = False,
        engine: BaseOCREngine | None = None,
    ) -> OCRResult:
        return extract_text(image_path, language=language, preprocess=preprocess, engine=engine)
