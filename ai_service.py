"""Gemini 3.7 Flash AI Service for Darfin Storage."""

import json
import logging
import httpx

from config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger(__name__)

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def is_ai_enabled() -> bool:
    return bool(GEMINI_API_KEY.strip())


async def _call_gemini(contents: list[dict], system_instruction: str = "") -> str | None:
    if not is_ai_enabled():
        return None

    params = {"key": GEMINI_API_KEY}
    payload: dict = {"contents": contents}

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GEMINI_URL, params=params, json=payload)
            if resp.status_code != 200:
                log.error("Gemini API error %s: %s", resp.status_code, resp.text)
                return None
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            return text.strip()
    except Exception as exc:
        log.error("Gemini call failed: %s", exc)
        return None


async def generate_smart_rename(file_name: str, file_bytes_b64: str | None = None,
                                mime_type: str | None = None) -> str | None:
    """Generate a clean, descriptive filename using Gemini 3.7 Flash."""
    parts = []
    if file_bytes_b64 and mime_type:
        parts.append({
            "inlineData": {
                "mimeType": mime_type,
                "data": file_bytes_b64,
            }
        })

    prompt = (
        f"Nama file saat ini: '{file_name}'.\n"
        "Berikan 1 usulan nama file baru yang sangat rapi, deskriptif, dan singkat berdasarkan gambar/nama file ini. "
        "Pertahankan atau sesuaikan ekstensi file yang sesuai. "
        "Format: jangan gunakan spasi, gunakan underscore atau pascal case (contoh: Struk_Belanja_Alfamart.jpg atau Laporan_Keuangan_Q3.pdf). "
        "Hanya berikan nama filenya saja, tanpa tanda kutip, tanpa kata pengantar atau penjelasan apapun."
    )
    parts.append({"text": prompt})

    result = await _call_gemini([{"parts": parts}])
    if result:
        # Clean potential markdown or quotes
        cleaned = result.replace("`", "").replace('"', '').replace("'", "").strip()
        # Keep single line
        cleaned = cleaned.split("\n")[0].strip()
        return cleaned
    return None


async def summarize_or_ocr(file_bytes_b64: str, mime_type: str, file_name: str) -> str | None:
    """Extract text (OCR) or summarize documents/images in clean Indonesian bullet points."""
    parts = [
        {
            "inlineData": {
                "mimeType": mime_type,
                "data": file_bytes_b64,
            }
        },
        {
            "text": (
                f"File: '{file_name}'.\n"
                "Jika ini adalah gambar dengan teks (seperti struk belanja, surat, KTP, invoice, formulir, atau screenshot), "
                "lakukan OCR untuk mengekstrak data penting dan angka-angka kunci.\n"
                "Jika ini dokumen atau catatan, berikan ringkasan poin-poin terpenting dalam bahasa Indonesia yang ramah, "
                "padat, dan mudah dibaca.\n"
                "Gunakan format Markdown rapi dengan emoji."
            )
        }
    ]
    return await _call_gemini([{"parts": parts}])


async def semantic_search(query: str, files_metadata: list[dict]) -> list[int]:
    """Find and rank matching file IDs using Gemini 3.7 Flash reasoning."""
    if not files_metadata or not is_ai_enabled():
        return []

    # Prepare compact list
    compact = [{"id": f["id"], "name": f["file_name"], "type": f["file_type"]} for f in files_metadata[:60]]
    prompt = (
        f"Pencarian pengguna: \"{query}\"\n"
        f"Daftar file yang ada di storage:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        "Pilih file yang paling relevan dengan maksud pencarian pengguna (bisa berdasarkan arti kata, kategori, atau nama).\n"
        "Kembalikan HANYA format JSON array berisi ID integer yang cocok, terurut dari yang paling relevan. "
        "Contoh: [12, 5, 23]\n"
        "Jika tidak ada yang cocok sama sekali, kembalikan []."
    )

    result = await _call_gemini([{"parts": [{"text": prompt}]}])
    if not result:
        return []

    try:
        cleaned = result.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [int(x) for x in data if isinstance(x, (int, str)) and str(x).isdigit()]
    except Exception as exc:
        log.warning("Failed to parse semantic search JSON: %s (raw: %s)", exc, result)

    return []
