"""Optional Tesseract OCR. Absent Tesseract, image paths degrade honestly."""

from __future__ import annotations

from typing import Any


def ocr_pil_image(image: Any) -> tuple[str, bool]:
    try:
        import pytesseract
    except ImportError:
        return "", False
    try:
        text = pytesseract.image_to_string(image)
    except Exception:
        return "", False
    return text or "", True
