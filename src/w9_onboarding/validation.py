"""Field-level validation and quality flags.

Extraction says "I saw this." Validation says "this is allowed to become
a supplier." Flags are stable machine-readable codes so downstream can
route on them (e.g. open a review task on MISSING_SIGNATURE).

Downstream should not re-implement TIN format or signature checks.
"""

from __future__ import annotations

from w9_onboarding.models import (
    ExtractedFields,
    FlagSeverity,
    TinType,
    ValidationFlag,
    ValidationResult,
)
from w9_onboarding.normalize import normalize_classification
from w9_onboarding.security import looks_like_ein_format, looks_like_ssn_format, normalize_tin

# Valid USPS state / DC abbreviations for a quick address sanity check.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def validate(
    fields: ExtractedFields,
    detected_form: str,
    form_revision: str | None,
    quality_score: float,
    disagreements: list[str],
) -> ValidationResult:
    """Build validation flags for one extracted W-9.

    ERROR flags set `blocking=True` and prevent automatic create/update.
    WARNING / INFO flags are advisory for reviewers and ops dashboards.
    """
    flags: list[ValidationFlag] = []

    # A W-8 (foreign) or unknown form must not create a US supplier record.
    if detected_form != "W-9":
        flags.append(
            ValidationFlag(
                code="WRONG_FORM",
                severity=FlagSeverity.ERROR,
                message=f"Document looks like {detected_form}, not a W-9.",
            )
        )

    # Line 1 is required for IRS TIN Matching in production.
    if not fields.legal_name.filled():
        flags.append(
            ValidationFlag(
                code="MISSING_LEGAL_NAME",
                severity=FlagSeverity.ERROR,
                message="Line 1 legal name is required for TIN Matching.",
                field="legal_name",
            )
        )

    # Tax identity: missing or bad format blocks auto onboarding.
    tin_digits = normalize_tin(fields.tin.value)
    if not tin_digits:
        flags.append(
            ValidationFlag(
                code="MISSING_TIN",
                severity=FlagSeverity.ERROR,
                message="No Taxpayer Identification Number was extracted.",
                field="tin",
            )
        )
    else:
        flags.extend(_tin_flags(fields, tin_digits))

    # Address issues are warnings — pay-to risk, but not always blocking alone.
    if not fields.address.street.filled() or not fields.address.city.filled():
        flags.append(
            ValidationFlag(
                code="INCOMPLETE_ADDRESS",
                severity=FlagSeverity.WARNING,
                message="Street or city is missing.",
                field="address",
            )
        )
    state = (fields.address.state.value or "").upper()
    if state and state not in US_STATES:
        flags.append(
            ValidationFlag(
                code="INVALID_STATE",
                severity=FlagSeverity.WARNING,
                message=f"State '{state}' is not a USPS abbreviation.",
                field="address.state",
            )
        )
    zip_code = fields.address.zip.value or ""
    if zip_code and not _valid_zip(zip_code):
        flags.append(
            ValidationFlag(
                code="INVALID_ZIP",
                severity=FlagSeverity.WARNING,
                message=f"ZIP '{zip_code}' is not a 5 or 9 digit US ZIP.",
                field="address.zip",
            )
        )

    # An unsigned W-9 is not a valid tax certification.
    if fields.signature_present.value != "true":
        flags.append(
            ValidationFlag(
                code="MISSING_SIGNATURE",
                severity=FlagSeverity.ERROR,
                message="Unsigned W-9 is invalid for tax reporting.",
                field="signature_present",
            )
        )
    if not fields.signature_date.filled():
        flags.append(
            ValidationFlag(
                code="MISSING_SIGNATURE_DATE",
                severity=FlagSeverity.WARNING,
                message="Certification date is missing.",
                field="signature_date",
            )
        )

    # Older revisions are fine; note that Line 3b will be absent.
    if form_revision and ("2018" in form_revision or "2017" in form_revision):
        flags.append(
            ValidationFlag(
                code="LEGACY_FORM_REVISION",
                severity=FlagSeverity.INFO,
                message=f"Older W-9 revision detected ({form_revision}). Line 3b will be absent.",
                field="form_revision",
            )
        )

    if quality_score < 0.4:
        flags.append(
            ValidationFlag(
                code="LOW_DOCUMENT_QUALITY",
                severity=FlagSeverity.WARNING,
                message="Text recovery quality is low; extraction may be incomplete.",
            )
        )

    # Heuristic vs LLM fought on a field — raise review awareness.
    for field_name in disagreements:
        flags.append(
            ValidationFlag(
                code="EXTRACTOR_DISAGREEMENT",
                severity=FlagSeverity.WARNING,
                message=f"Heuristic and LLM extractors disagreed on {field_name}.",
                field=field_name,
            )
        )

    blocking = any(f.severity == FlagSeverity.ERROR for f in flags)
    passed = not blocking
    return ValidationResult(passed=passed, blocking=blocking, flags=flags)


def _tin_flags(fields: ExtractedFields, digits: str) -> list[ValidationFlag]:
    """Local TIN format checks only — IRS TIN Matching is a production adapter."""
    flags: list[ValidationFlag] = []
    tin_type = fields.tin.tin_type
    if tin_type == TinType.SSN and not looks_like_ssn_format(digits):
        flags.append(
            ValidationFlag(
                code="TIN_FORMAT_INVALID",
                severity=FlagSeverity.ERROR,
                message="SSN fails basic area/group/serial checks.",
                field="tin",
            )
        )
    elif tin_type == TinType.EIN and not looks_like_ein_format(digits):
        flags.append(
            ValidationFlag(
                code="TIN_FORMAT_INVALID",
                severity=FlagSeverity.ERROR,
                message="EIN is not 9 digits.",
                field="tin",
            )
        )
    elif len(digits) != 9:
        flags.append(
            ValidationFlag(
                code="TIN_FORMAT_INVALID",
                severity=FlagSeverity.ERROR,
                message="TIN is not 9 digits.",
                field="tin",
            )
        )
    else:
        flags.append(
            ValidationFlag(
                code="TIN_FORMAT_VALID",
                severity=FlagSeverity.INFO,
                message="TIN has a valid format. IRS TIN Matching is not called in this prototype.",
                field="tin",
            )
        )

    # Soft check: a C-Corp with an SSN is usually a data-entry mistake.
    classification = normalize_classification(fields.tax_classification.value)
    entity_classes = {
        "C_CORPORATION",
        "S_CORPORATION",
        "PARTNERSHIP",
        "TRUST_ESTATE",
        "LLC",
    }
    if classification in entity_classes and tin_type == TinType.SSN:
        flags.append(
            ValidationFlag(
                code="TIN_TYPE_CLASSIFICATION_MISMATCH",
                severity=FlagSeverity.WARNING,
                message="Entity classification usually uses an EIN, not an SSN.",
                field="tin",
            )
        )
    return flags


def _valid_zip(value: str) -> bool:
    """Accept 5-digit or ZIP+4 forms."""
    compact = value.replace(" ", "")
    return bool(
        __import__("re").fullmatch(r"\d{5}(-\d{4})?", compact)
    )
