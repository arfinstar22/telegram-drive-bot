"""Local OCR Engine Abstractions and Tesseract Implementation (Task 3A).

Provides:
- BaseOCREngine: Abstract interface for local OCR implementations
- LocalTesseractEngine: Native subprocess-based Tesseract runner with TSV confidence parsing
- MockOCREngine: In-memory deterministic engine for offline unit tests and CI
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from darfin_intelligence.ocr.models import OCRBlock

log = logging.getLogger(__name__)


class BaseOCREngine(ABC):
    """Abstract base class for local OCR engines."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Name of the engine (e.g. 'tesseract', 'mock')."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the OCR engine binary/runtime is available in this environment."""
        pass

    @abstractmethod
    def get_version(self) -> str | None:
        """Get the detected engine version or None if unavailable."""
        pass

    @abstractmethod
    def get_supported_languages(self) -> list[str]:
        """List language codes supported and installed for this engine."""
        pass

    @abstractmethod
    def extract(
        self,
        image_path: str,
        language: str = "eng",
        timeout_seconds: int = 15,
    ) -> tuple[str, float | None, list[OCRBlock]]:
        """Extract text from an image file.

        Returns:
            tuple: (raw_text, confidence_score_0_to_1, list_of_blocks)
        """
        pass


class LocalTesseractEngine(BaseOCREngine):
    """Local Tesseract OCR engine executed via standard library subprocess.

    Zero third-party wrappers, zero cloud dependencies.
    Extracts text and per-line/block confidence using Tesseract TSV output.
    """

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        self._cmd = tesseract_cmd or os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        self._cached_version: str | None = None
        self._cached_langs: list[str] | None = None

    @property
    def engine_name(self) -> str:
        return "tesseract"

    def is_available(self) -> bool:
        if not self._cmd:
            self._cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        if not self._cmd:
            return False
        return os.path.isfile(self._cmd) and os.access(self._cmd, os.X_OK)

    def get_version(self) -> str | None:
        if self._cached_version is not None:
            return self._cached_version
        if not self.is_available():
            return None

        try:
            res = subprocess.run(
                [self._cmd, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            # Example output: "tesseract 5.3.4\n leptonica-1.84.1..."
            first_line = (res.stdout or res.stderr or "").strip().split("\n")[0]
            m = re.search(r"tesseract\s+([0-9a-zA-Z\.\-]+)", first_line, re.IGNORECASE)
            self._cached_version = m.group(1) if m else first_line
            return self._cached_version
        except Exception as exc:
            log.debug("Failed to detect Tesseract version: %s", exc)
            return None

    def get_supported_languages(self) -> list[str]:
        if self._cached_langs is not None:
            return self._cached_langs
        if not self.is_available():
            return []

        try:
            res = subprocess.run(
                [self._cmd, "--list-langs"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            lines = (res.stdout or "").strip().split("\n")
            # First line is usually "List of available languages (X):"
            langs: list[str] = []
            for line in lines:
                code = line.strip().lower()
                if code and not code.startswith("list of"):
                    langs.append(code)
            self._cached_langs = langs
            return langs
        except Exception as exc:
            log.debug("Failed to list Tesseract languages: %s", exc)
            return []

    def extract(
        self,
        image_path: str,
        language: str = "eng",
        timeout_seconds: int = 15,
    ) -> tuple[str, float | None, list[OCRBlock]]:
        if not self.is_available():
            raise RuntimeError("Local Tesseract OCR engine is not installed or available.")

        # Execute tesseract in TSV mode to capture text and word/line confidences
        # Command: tesseract <image_path> stdout -l <language> tsv
        cmd = [self._cmd, image_path, "stdout", "-l", language, "tsv"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )

        if res.returncode != 0:
            err = (res.stderr or "").strip()
            raise RuntimeError(f"Tesseract returned exit code {res.returncode}: {err}")

        tsv_data = res.stdout or ""
        return self._parse_tsv_output(tsv_data, image_path, language, timeout_seconds)

    def _parse_tsv_output(
        self,
        tsv_data: str,
        image_path: str,
        language: str,
        timeout_seconds: int,
    ) -> tuple[str, float | None, list[OCRBlock]]:
        lines = tsv_data.splitlines()
        if len(lines) <= 1:
            # Fall back to plain text mode if TSV has only header
            return self._extract_plain_text(image_path, language, timeout_seconds)

        header = [h.strip() for h in lines[0].split("\t")]
        try:
            conf_idx = header.index("conf")
            text_idx = header.index("text")
            line_idx = header.index("line_num")
            left_idx = header.index("left")
            top_idx = header.index("top")
            width_idx = header.index("width")
            height_idx = header.index("height")
        except ValueError:
            return self._extract_plain_text(image_path, language, timeout_seconds)

        # Group words by line_num
        current_line_num: int | None = None
        line_words: list[str] = []
        line_confs: list[float] = []
        line_bboxes: list[tuple[int, int, int, int]] = []

        all_text_lines: list[str] = []
        blocks: list[OCRBlock] = []
        all_word_confs: list[float] = []

        def flush_line():
            nonlocal current_line_num, line_words, line_confs, line_bboxes
            if not line_words:
                return
            line_text = " ".join(line_words).strip()
            if line_text:
                all_text_lines.append(line_text)
                avg_line_conf = sum(line_confs) / max(1, len(line_confs))
                # Compute composite bounding box
                min_l = min(b[0] for b in line_bboxes)
                min_t = min(b[1] for b in line_bboxes)
                max_r = max(b[0] + b[2] for b in line_bboxes)
                max_b = max(b[1] + b[3] for b in line_bboxes)
                box = (min_l, min_t, max_r - min_l, max_b - min_t)
                blocks.append(
                    OCRBlock(
                        text=line_text,
                        confidence=round(avg_line_conf, 2),
                        line_num=current_line_num,
                        bbox=box,
                    )
                )
            line_words = []
            line_confs = []
            line_bboxes = []

        for row in lines[1:]:
            parts = row.split("\t")
            if len(parts) <= max(conf_idx, text_idx):
                continue

            raw_conf = parts[conf_idx].strip()
            raw_wtext = parts[text_idx].strip()
            raw_lnum = parts[line_idx].strip()

            try:
                conf_val = float(raw_conf)
                lnum_val = int(raw_lnum) if raw_lnum.isdigit() else 0
            except ValueError:
                continue

            # Ignore structural markers with conf == -1
            if conf_val < 0 or not raw_wtext:
                continue

            try:
                l = int(parts[left_idx])
                t = int(parts[top_idx])
                w = int(parts[width_idx])
                h = int(parts[height_idx])
            except (ValueError, IndexError):
                l, t, w, h = 0, 0, 0, 0

            if current_line_num is not None and lnum_val != current_line_num:
                flush_line()

            current_line_num = lnum_val
            line_words.append(raw_wtext)
            line_confs.append(conf_val)
            line_bboxes.append((l, t, w, h))
            all_word_confs.append(conf_val)

        flush_line()

        raw_text = "\n".join(all_text_lines)
        overall_conf: float | None = None
        if all_word_confs:
            # Scale 0-100 percentage to 0.0-1.0
            overall_conf = round(sum(all_word_confs) / len(all_word_confs) / 100.0, 4)

        return raw_text, overall_conf, blocks

    def _extract_plain_text(
        self,
        image_path: str,
        language: str,
        timeout_seconds: int,
    ) -> tuple[str, float | None, list[OCRBlock]]:
        cmd = [self._cmd, image_path, "stdout", "-l", language]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            raise RuntimeError(f"Tesseract returned exit code {res.returncode}: {err}")
        return res.stdout or "", None, []


class MockOCREngine(BaseOCREngine):
    """Deterministic Mock OCR engine for testing, CI, and fixture validation."""

    def __init__(
        self,
        available: bool = True,
        version: str = "mock-1.0.0",
        supported_languages: list[str] | None = None,
    ) -> None:
        self._available = available
        self._version = version
        self._supported_languages = supported_languages or ["eng", "ind"]
        self._registered_results: dict[str, tuple[str, float | None, list[OCRBlock]]] = {}
        self._simulate_timeout = False
        self._simulate_error: str | None = None

    @property
    def engine_name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def get_version(self) -> str | None:
        return self._version if self._available else None

    def get_supported_languages(self) -> list[str]:
        return list(self._supported_languages)

    def set_simulate_timeout(self, timeout: bool) -> None:
        self._simulate_timeout = timeout

    def set_simulate_error(self, error: str | None) -> None:
        self._simulate_error = error

    def register_result(
        self,
        key: str,
        text: str,
        confidence: float | None = 0.95,
        blocks: list[OCRBlock] | None = None,
    ) -> None:
        """Register expected text for a given filename or substring key."""
        if blocks is None and text:
            blocks = [
                OCRBlock(
                    text=line,
                    confidence=95.0,
                    line_num=i + 1,
                    bbox=(10, 10 + i * 20, 200, 18),
                )
                for i, line in enumerate(text.splitlines())
                if line.strip()
            ]
        self._registered_results[key.lower()] = (text, confidence, blocks or [])

    def extract(
        self,
        image_path: str,
        language: str = "eng",
        timeout_seconds: int = 15,
    ) -> tuple[str, float | None, list[OCRBlock]]:
        if not self._available:
            raise RuntimeError("Mock OCR engine is marked unavailable.")

        if self._simulate_timeout:
            raise subprocess.TimeoutExpired(cmd=["mock_ocr"], timeout=timeout_seconds)

        if self._simulate_error:
            raise RuntimeError(self._simulate_error)

        # Match registered results by filename or substring
        lower_path = image_path.lower()
        basename = os.path.basename(lower_path)

        for key, res in self._registered_results.items():
            if key == "*" or key in basename or key in lower_path:
                return res

        # Default blank result for unregistered images
        return "", 0.0, []
