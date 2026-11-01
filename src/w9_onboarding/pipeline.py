"""End-to-end orchestration: ingest -> extract -> validate -> match."""

from __future__ import annotations

import uuid
from pathlib import Path

from w9_onboarding import SCHEMA_VERSION, __version__
from w9_onboarding.extraction import extract_fields
from w9_onboarding.ingestion import document_info, ingest
from w9_onboarding.master import load_supplier_master
from w9_onboarding.matching import match_supplier
from w9_onboarding.models import (
    AuditInfo,
    ExtractedFields,
    FieldValue,
    OnboardingResponse,
    SupplierRecord,
    utcnow,
)
from w9_onboarding.validation import validate


def process_document(
    document_path: str | Path,
    master: list[SupplierRecord] | str | Path,
    tenant_id: str = "demo-tenant",
    use_llm: bool = True,
) -> OnboardingResponse:
    if not isinstance(master, list):
        master = load_supplier_master(master)

    ingested = ingest(document_path)
    fields, detected, revision, extractor_path, disagreements = extract_fields(
        ingested.text, use_llm=use_llm
    )
    overall = score_overall_confidence(fields, ingested.quality_score, disagreements, detected)
    validation = validate(
        fields, detected, revision, ingested.quality_score, disagreements
    )
    match = match_supplier(fields, master, validation, overall, detected)
    info = document_info(ingested, detected, revision)

    return OnboardingResponse(
        request_id=str(uuid.uuid4()),
        schema_version=SCHEMA_VERSION,
        document=info,
        extraction=fields,
        overall_confidence=overall,
        validation=validation,
        match=match,
        audit=AuditInfo(
            processed_at=utcnow(),
            pipeline_version=__version__,
            schema_version=SCHEMA_VERSION,
            extractor_path=extractor_path,
            model_versions={"pipeline": __version__, "extractor": extractor_path},
            tenant_id=tenant_id,
        ),
    )


def score_overall_confidence(
    fields: ExtractedFields,
    quality_score: float,
    disagreements: list[str],
    detected_form: str,
) -> float:
    if detected_form != "W-9":
        return 0.2

    weighted: list[tuple[FieldValue, float]] = [
        (fields.legal_name, 0.25),
        (fields.tax_classification, 0.1),
        (fields.address.street, 0.1),
        (fields.address.city, 0.08),
        (fields.address.state, 0.07),
        (fields.address.zip, 0.07),
        (fields.signature_present, 0.08),
    ]
    score = 0.0
    for field, weight in weighted:
        score += weight * (field.confidence if field.filled() else 0.0)
    score += 0.25 * fields.tin.confidence
    score = 0.8 * score + 0.2 * quality_score
    if disagreements:
        score *= 0.85
    return round(max(0.0, min(score, 1.0)), 3)
