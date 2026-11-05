"""End-to-end orchestration: ingest -> extract -> validate -> match.

This is the main entry used by the CLI. It does not write the supplier
master. It returns an OnboardingResponse JSON object that a downstream
PairSoft product would act on (create / update / open a review task).
"""

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
    """Run the full W-9 onboarding pipeline on one document.

    Steps:
      1. Load the tenant supplier master (CSV/JSON stand-in for a real API)
      2. Ingest the PDF/image and recover text
      3. Extract fields (heuristic parser, optional LLM refine)
      4. Score overall confidence
      5. Validate (signature, TIN format, wrong form, etc.)
      6. Match against the master and decide create / update / review
    """
    # Accept either an already-loaded list or a path to the master file.
    if not isinstance(master, list):
        master = load_supplier_master(master)

    # Step 1–2: open the file and recover page text.
    ingested = ingest(document_path)

    # Step 3: pull Line 1–7 style fields out of the recovered text.
    fields, detected, revision, extractor_path, disagreements = extract_fields(
        ingested.text, use_llm=use_llm
    )

    # Step 4: blend field confidences + document quality into one score.
    overall = score_overall_confidence(fields, ingested.quality_score, disagreements, detected)

    # Step 5: machine-readable flags (errors block auto create/update).
    validation = validate(
        fields, detected, revision, ingested.quality_score, disagreements
    )

    # Step 6: rules decide — models never pick create vs update.
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
    """Weighted confidence used as a gate before auto create/update.

    This is not an LLM self-score. It blends required-field confidences,
    document text quality, and a penalty when extractors disagree.
    """
    # Wrong form: do not pretend we have a trustworthy US supplier identity.
    if detected_form != "W-9":
        return 0.2

    # Legal name and TIN dominate; address pieces and signature fill the rest.
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

    # Document quality (text layer / OCR) can pull the overall score down.
    score = 0.8 * score + 0.2 * quality_score
    if disagreements:
        score *= 0.85
    return round(max(0.0, min(score, 1.0)), 3)
