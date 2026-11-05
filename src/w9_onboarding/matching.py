"""Match extracted W-9 data to a tenant supplier master.

This is the decision engine. Models extract fields; *this module* decides
CREATE_NEW / UPDATE_EXISTING / HUMAN_REVIEW.

Decision rules (opinionated):

1. TIN is the strongest key and is never sufficient alone.
2. Same TIN + same normalized name + no material change -> UPDATE.
3. Same TIN + same name + material change -> HUMAN_REVIEW.
4. Same TIN + different name -> HUMAN_REVIEW (fraud or legal rename).
5. No TIN match + very high name and address similarity -> HUMAN_REVIEW
   (possible duplicate or TIN typo). Do not auto-create or auto-update.
6. No meaningful candidate -> CREATE_NEW, unless extraction/validation
   is too weak to trust a new master record.
7. Ambiguous near-ties among candidates -> HUMAN_REVIEW.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from w9_onboarding.models import (
    ExtractedFields,
    MatchCandidate,
    MatchDecision,
    MatchResult,
    SupplierRecord,
    ValidationResult,
)
from w9_onboarding.normalize import (
    names_equivalent,
    normalize_classification,
    normalize_name,
    normalize_state,
    normalize_street,
    normalize_zip,
)
from w9_onboarding.security import normalize_tin, redact_tin

# Similarity thresholds used by the match policy below.
NAME_STRONG = 0.92
NAME_MEDIUM = 0.80
ADDRESS_STRONG = 0.90
AMBIGUITY_DELTA = 0.08  # two candidates this close → ask a human
REVIEW_CONFIDENCE_FLOOR = 0.62  # below this, do not auto-act


@dataclass
class Scored:
    """One master row scored against the extracted W-9 identity."""

    record: SupplierRecord
    tin_match: bool
    name_score: float
    address_score: float
    composite: float


def match_supplier(
    fields: ExtractedFields,
    master: list[SupplierRecord],
    validation: ValidationResult,
    overall_confidence: float,
    detected_form: str,
) -> MatchResult:
    """Return create / update / review for this W-9 against the tenant master."""

    # Gate 1: only onboard US suppliers from a W-9.
    if detected_form != "W-9":
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.95,
            "WRONG_FORM",
            "Document is not a W-9. Downstream should not create or update a US supplier from it.",
            [],
        )

    # Gate 2: if we barely read the form, stop and ask a person.
    if overall_confidence < REVIEW_CONFIDENCE_FLOOR:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            overall_confidence,
            "LOW_EXTRACTION_CONFIDENCE",
            "Extraction confidence is below the auto-decision floor. A reviewer should confirm the fields first.",
            [],
        )

    # Gate 3: missing identity fields cannot become an auto create/update.
    blocking_codes = {flag.code for flag in validation.flags if flag.severity.value == "error"}
    hard_blockers = blocking_codes & {"MISSING_LEGAL_NAME", "MISSING_TIN", "TIN_FORMAT_INVALID"}
    if hard_blockers:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.7,
            "BLOCKING_VALIDATION",
            "Blocking validation flags prevent an automatic create or update: "
            + ", ".join(sorted(hard_blockers))
            + ".",
            [],
        )

    # Score every master row; TIN hits sort first.
    scored = [_score(fields, record) for record in master]
    scored.sort(key=lambda item: (item.tin_match, item.composite, item.name_score), reverse=True)
    candidates = [_to_candidate(item) for item in scored[:5] if item.composite >= 0.35 or item.tin_match]

    # Path A: exact TIN found in this tenant's master.
    tin_hits = [item for item in scored if item.tin_match]
    if tin_hits:
        return _from_tin_match(fields, tin_hits, candidates)

    # Path B: no TIN hit — decide create vs possible-duplicate review.
    if not candidates:
        if "MISSING_SIGNATURE" in blocking_codes:
            return _decision(
                MatchDecision.HUMAN_REVIEW,
                0.72,
                "NEW_BUT_UNSIGNED",
                "No supplier match, but the W-9 is unsigned so a new master record should not be auto-created.",
                [],
            )
        return _decision(
            MatchDecision.CREATE_NEW,
            0.86,
            "NO_MATCH",
            "No TIN match and no strong name/address candidate. Treat as a new supplier.",
            [],
        )

    top = scored[0]
    second = scored[1] if len(scored) > 1 else None

    # Same name + address, different TIN → classic duplicate risk.
    if (
        top.name_score >= NAME_STRONG
        and top.address_score >= ADDRESS_STRONG
    ):
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.78,
            "POSSIBLE_DUPLICATE",
            (
                f"No TIN match, but name and address are very close to {top.record.supplier_id} "
                f"({top.record.legal_name}). Could be a duplicate, a TIN typo, or a related entity."
            ),
            candidates,
            matched=top.record.supplier_id,
        )

    # Two near-tied candidates → reviewer picks.
    if top.name_score >= NAME_MEDIUM and second and abs(top.composite - second.composite) < AMBIGUITY_DELTA:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.6,
            "AMBIGUOUS_CANDIDATES",
            (
                f"Several suppliers have similar names, led by {top.record.supplier_id} "
                f"and {second.record.supplier_id}. A reviewer should pick the record."
            ),
            candidates,
        )

    # Name-only similarity without TIN is too weak for auto-action.
    if top.name_score >= NAME_MEDIUM:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.64,
            "NAME_ONLY_CANDIDATE",
            (
                f"Name is similar to {top.record.supplier_id} without a TIN match. "
                "Too risky to auto-create or auto-update."
            ),
            candidates,
            matched=top.record.supplier_id,
        )

    if "MISSING_SIGNATURE" in blocking_codes:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.7,
            "NEW_BUT_UNSIGNED",
            "Looks like a new supplier, but the form is unsigned.",
            candidates,
        )

    return _decision(
        MatchDecision.CREATE_NEW,
        0.8,
        "NO_MATCH",
        "Remaining candidates are weak. Treat as a new supplier.",
        candidates,
    )


def _from_tin_match(
    fields: ExtractedFields,
    tin_hits: list[Scored],
    candidates: list[MatchCandidate],
) -> MatchResult:
    """Handle the case where the extracted TIN already exists on the master.

    TIN match is necessary for UPDATE_EXISTING, but never sufficient alone.
    Name must agree, and material changes (address, classification, DBA)
    go to HUMAN_REVIEW instead of a silent update.
    """
    # Same TIN on multiple master rows is a data-quality problem, not auto-merge.
    if len(tin_hits) > 1:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.9,
            "DUPLICATE_TIN_IN_MASTER",
            "The extracted TIN already exists on more than one supplier record. Master data needs cleanup.",
            candidates,
            matched=tin_hits[0].record.supplier_id,
        )

    hit = tin_hits[0]
    material = _material_changes(fields, hit.record)
    name_ok = hit.name_score >= NAME_STRONG or names_equivalent(fields.legal_name.value, hit.record.legal_name)
    dba_ok = (
        not fields.dba_name.filled()
        or not hit.record.dba
        or fuzz.token_sort_ratio(
            normalize_name(fields.dba_name.value), normalize_name(hit.record.dba)
        )
        >= 88
    )

    # Same TIN, different legal name → fraud signal or unreported rename.
    if not name_ok:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.88,
            "TIN_NAME_CONFLICT",
            (
                f"TIN matches {hit.record.supplier_id} ({hit.record.legal_name}) but the legal name "
                f"does not. This is a fraud signal or an unreported legal rename."
            ),
            candidates,
            matched=hit.record.supplier_id,
            changes=material,
        )

    # Same identity, but pay-to / tax posture changed → review before writing.
    if material:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.84,
            "MATERIAL_CHANGE",
            (
                f"TIN and name match {hit.record.supplier_id}, but material fields changed: "
                f"{', '.join(material)}. Route to review before updating pay-to data."
            ),
            candidates,
            matched=hit.record.supplier_id,
            changes=material,
        )

    if not dba_ok:
        return _decision(
            MatchDecision.HUMAN_REVIEW,
            0.76,
            "MATERIAL_CHANGE",
            f"DBA differs from {hit.record.supplier_id}. Treat as a material identity change.",
            candidates,
            matched=hit.record.supplier_id,
            changes=["dba_name"],
        )

    # Boring happy path: same TIN, same name, nothing material changed.
    return _decision(
        MatchDecision.UPDATE_EXISTING,
        0.93,
        "EXACT_TIN_AND_NAME",
        (
            f"TIN and legal name match {hit.record.supplier_id} with no material changes. "
            "Safe to treat as a resubmitted W-9 for the existing supplier."
        ),
        candidates,
        matched=hit.record.supplier_id,
    )


def _score(fields: ExtractedFields, record: SupplierRecord) -> Scored:
    """Compare one extracted W-9 to one master row."""
    extracted_tin = normalize_tin(fields.tin.value)
    record_tin = normalize_tin(record.tin)
    tin_match = bool(extracted_tin and record_tin and extracted_tin == record_tin)

    # Compare legal name and DBA both ways (either side may carry the trade name).
    extracted_names = [normalize_name(fields.legal_name.value)]
    if fields.dba_name.filled():
        extracted_names.append(normalize_name(fields.dba_name.value))
    record_names = [normalize_name(record.legal_name)]
    if record.dba:
        record_names.append(normalize_name(record.dba))

    name_score = 0.0
    for left in extracted_names:
        for right in record_names:
            if not left or not right:
                continue
            name_score = max(name_score, fuzz.token_sort_ratio(left, right) / 100.0)

    address_score = _address_score(fields, record)
    # TIN match dominates; name and address break ties and catch conflicts.
    if tin_match:
        composite = 0.7 + 0.2 * name_score + 0.1 * address_score
    else:
        composite = 0.65 * name_score + 0.35 * address_score
    return Scored(
        record=record,
        tin_match=tin_match,
        name_score=round(name_score, 3),
        address_score=round(address_score, 3),
        composite=round(min(composite, 1.0), 3),
    )


def _address_score(fields: ExtractedFields, record: SupplierRecord) -> float:
    """Street-weighted address similarity (street 50%, city/state/ZIP the rest)."""
    street = 0.0
    if fields.address.street.value and record.street:
        street = fuzz.token_sort_ratio(
            normalize_street(fields.address.street.value),
            normalize_street(record.street),
        ) / 100.0
    city = 1.0 if _eq(fields.address.city.value, record.city) else 0.0
    if fields.address.city.value and record.city:
        city = fuzz.ratio(
            (fields.address.city.value or "").upper(),
            record.city.upper(),
        ) / 100.0
    state = 1.0 if normalize_state(fields.address.state.value) == normalize_state(record.state) and record.state else 0.0
    zip_score = 1.0 if normalize_zip(fields.address.zip.value) and normalize_zip(fields.address.zip.value) == normalize_zip(record.zip) else 0.0
    return 0.5 * street + 0.2 * city + 0.15 * state + 0.15 * zip_score


def _material_changes(fields: ExtractedFields, record: SupplierRecord) -> list[str]:
    """Fields that must not silently update pay-to or tax posture.

    Address / ZIP changes can redirect payments. Classification changes
    affect 1099 posture. Both require a human before writing the master.
    """
    changes: list[str] = []
    extracted_zip = normalize_zip(fields.address.zip.value)
    record_zip = normalize_zip(record.zip)
    street_changed = False
    if record.street and fields.address.street.value:
        street_score = fuzz.token_sort_ratio(
            normalize_street(fields.address.street.value),
            normalize_street(record.street),
        )
        street_changed = street_score < 86
    zip_changed = bool(extracted_zip and record_zip and extracted_zip != record_zip)
    if street_changed or zip_changed:
        changes.append("address")
    extracted_class = normalize_classification(fields.tax_classification.value)
    record_class = normalize_classification(record.tax_classification)
    if extracted_class != "UNKNOWN" and record_class != "UNKNOWN" and extracted_class != record_class:
        changes.append("tax_classification")
    return changes


def _eq(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().upper() == b.strip().upper())


def _to_candidate(item: Scored) -> MatchCandidate:
    """Public candidate row: TIN is always redacted in the response."""
    digits = normalize_tin(item.record.tin)
    return MatchCandidate(
        supplier_id=item.record.supplier_id,
        legal_name=item.record.legal_name,
        tin_redacted=redact_tin(digits, item.record.tin_type) if digits else None,
        tin_match=item.tin_match,
        name_score=item.name_score,
        address_score=item.address_score,
        composite_score=item.composite,
        status=item.record.status,
    )


def _decision(
    decision: MatchDecision,
    confidence: float,
    reason_code: str,
    reasoning: str,
    candidates: list[MatchCandidate],
    matched: str | None = None,
    changes: list[str] | None = None,
) -> MatchResult:
    """Build the MatchResult block of the API response."""
    return MatchResult(
        decision=decision,
        confidence=round(confidence, 3),
        reason_code=reason_code,
        reasoning=reasoning,
        matched_supplier_id=matched,
        material_changes=changes or [],
        candidates=candidates,
    )
