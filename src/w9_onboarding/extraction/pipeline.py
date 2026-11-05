"""Extraction orchestration: heuristic parser + optional LLM refine.

Production would put Azure Document Intelligence behind the same
ExtractedFields shape. This prototype keeps a local parser so the case
study runs without cloud credentials.
"""

from __future__ import annotations

from w9_onboarding.extraction.consensus import merge_extractions
from w9_onboarding.extraction.form_parser import parse_w9_text
from w9_onboarding.extraction.llm_extractor import extract_with_llm
from w9_onboarding.models import ExtractedFields


def extract_fields(
    text: str,
    use_llm: bool = True,
) -> tuple[ExtractedFields, str, str | None, str, list[str]]:
    """Extract W-9 fields from recovered document text.

    Returns:
      fields          — structured ExtractedFields with per-field confidence
      detected_form   — "W-9", "W-8", or "UNKNOWN"
      revision        — e.g. "2024-March" or "2018-October"
      extractor_path  — "heuristic" or "heuristic+llm:<model>"
      disagreements   — field names where heuristic and LLM disagreed
    """
    # Always run the label-aware local parser (DI stand-in).
    heuristic, detected, revision, _ = parse_w9_text(text)
    path = "heuristic"
    disagreements: list[str] = []

    # Optional second pass: LLM normalizes / fills gaps from the same text.
    # Off unless --use-llm is passed (and OPENAI_API_KEY is set).
    llm_result = extract_with_llm(text) if use_llm else None
    if llm_result:
        llm_fields, llm_form, llm_revision, model = llm_result
        merged, disagreements = merge_extractions(heuristic, llm_fields)
        detected = detected if detected != "UNKNOWN" else (llm_form or "UNKNOWN")
        revision = revision or llm_revision
        path = f"heuristic+llm:{model}"
        return merged, detected, revision, path, disagreements

    return heuristic, detected, revision, path, disagreements
