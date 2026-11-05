"""Ingest a local W-9 file and recover page text.

First stage of the pipeline: open the file, detect type, pull text.

Production would also run virus scan, deeper type sniffing, and image
quality scoring here. The prototype does honest format detection and
text recovery so the rest of the pipeline has something to parse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from w9_onboarding.models import DocumentInfo

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}


@dataclass
class IngestedDocument:
    """Raw ingest result passed to extraction.

    `quality_score` is used later when computing overall confidence.
    `used_ocr` is true when we had to fall back from a missing PDF text layer.
    """

    path: Path
    media_type: str
    page_count: int
    text: str
    quality_score: float
    quality_issues: list[str] = field(default_factory=list)
    used_ocr: bool = False


def ingest(path: str | Path) -> IngestedDocument:
    """Open a PDF or image and return recovered text + a quality score."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _ingest_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return _ingest_image(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def _ingest_pdf(path: Path) -> IngestedDocument:
    """Prefer the digital text layer; OCR only if the PDF is a scan."""
    issues: list[str] = []
    text = _pdfplumber_text(path)
    page_count = _page_count(path)
    if not text.strip():
        # Scanned PDF: try OCR if Tesseract / pypdfium2 are available.
        ocr_text, ocr_ok = _ocr_pdf(path)
        if ocr_ok and ocr_text.strip():
            text = ocr_text
            issues.append("pdf_had_no_text_layer_used_ocr")
            return IngestedDocument(
                path=path,
                media_type="application/pdf",
                page_count=page_count,
                text=text,
                quality_score=0.55,
                quality_issues=issues,
                used_ocr=True,
            )
        # Do not invent text — mark low quality and let matching go to review.
        issues.append("no_extractable_text")
        return IngestedDocument(
            path=path,
            media_type="application/pdf",
            page_count=page_count,
            text="",
            quality_score=0.15,
            quality_issues=issues,
        )
    quality = _text_quality(text)
    if len(text) < 120:
        issues.append("short_text_layer")
        quality = min(quality, 0.45)
    return IngestedDocument(
        path=path,
        media_type="application/pdf",
        page_count=page_count,
        text=text,
        quality_score=quality,
        quality_issues=issues,
    )


def _ingest_image(path: Path) -> IngestedDocument:
    text, ok = _ocr_image(path)
    issues = [] if ok else ["ocr_unavailable"]
    quality = _text_quality(text) if text else 0.2
    if not ok:
        quality = 0.1
    return IngestedDocument(
        path=path,
        media_type=f"image/{path.suffix.lower().lstrip('.')}",
        page_count=1,
        text=text,
        quality_score=quality,
        quality_issues=issues,
        used_ocr=ok,
    )


def _pdfplumber_text(path: Path) -> str:
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def _page_count(path: Path) -> int:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 1


def _ocr_pdf(path: Path) -> tuple[str, bool]:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return "", False
    try:
        from w9_onboarding.extraction.ocr import ocr_pil_image
    except Exception:
        return "", False
    texts = []
    doc = pdfium.PdfDocument(str(path))
    for index in range(len(doc)):
        page = doc[index]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil()
        page_text, ok = ocr_pil_image(image)
        if not ok:
            return "", False
        texts.append(page_text)
    return "\n".join(texts), True


def _ocr_image(path: Path) -> tuple[str, bool]:
    try:
        from PIL import Image

        from w9_onboarding.extraction.ocr import ocr_pil_image
    except Exception:
        return "", False
    image = Image.open(path)
    return ocr_pil_image(image)


def _text_quality(text: str) -> float:
    if not text.strip():
        return 0.0
    letters = sum(ch.isalpha() for ch in text)
    ratio = letters / max(len(text), 1)
    length_score = min(len(text) / 800, 1.0)
    return round(min(1.0, 0.4 * ratio + 0.6 * length_score), 3)


def document_info(ingested: IngestedDocument, detected_form: str, revision: str | None) -> DocumentInfo:
    return DocumentInfo(
        filename=ingested.path.name,
        media_type=ingested.media_type,
        detected_form=detected_form,  # type: ignore[arg-type]
        form_revision=revision,
        page_count=ingested.page_count,
        quality_score=ingested.quality_score,
        quality_issues=list(ingested.quality_issues),
    )
