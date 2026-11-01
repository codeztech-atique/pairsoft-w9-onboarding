"""Versioned API contract for the W-9 onboarding service.

Downstream consumers should treat this module as the source of truth.
Unknown future fields must be ignored; required fields in 1.0 will not
be removed without a schema_version bump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from w9_onboarding import SCHEMA_VERSION


class TaxClassification(str, Enum):
    INDIVIDUAL_SOLE_PROPRIETOR = "INDIVIDUAL_SOLE_PROPRIETOR"
    C_CORPORATION = "C_CORPORATION"
    S_CORPORATION = "S_CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    TRUST_ESTATE = "TRUST_ESTATE"
    LLC = "LLC"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class LlcClassification(str, Enum):
    C = "C"
    S = "S"
    P = "P"


class TinType(str, Enum):
    EIN = "EIN"
    SSN = "SSN"
    UNKNOWN = "UNKNOWN"


class MatchDecision(str, Enum):
    CREATE_NEW = "CREATE_NEW"
    UPDATE_EXISTING = "UPDATE_EXISTING"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class FlagSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FieldSource(str, Enum):
    HEURISTIC = "heuristic"
    LLM = "llm"
    CONSENSUS = "consensus"
    OCR = "ocr"
    NONE = "none"


class FieldValue(BaseModel):
    """A single extracted value plus the quality signal for that value."""

    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source: FieldSource = FieldSource.NONE

    def filled(self) -> bool:
        return bool(self.value and str(self.value).strip())


class TinValue(BaseModel):
    """TIN is returned for downstream writes and redacted for logs.

    `value` is the normalized display form (EIN xx-xxxxxxx / SSN xxx-xx-xxxx)
    when extraction succeeded. Logs and printed CLI output should use
    `value_redacted` only.
    """

    value: Optional[str] = None
    value_redacted: Optional[str] = None
    last4: Optional[str] = None
    tin_type: TinType = TinType.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source: FieldSource = FieldSource.NONE


class AddressFields(BaseModel):
    street: FieldValue = Field(default_factory=FieldValue)
    city: FieldValue = Field(default_factory=FieldValue)
    state: FieldValue = Field(default_factory=FieldValue)
    zip: FieldValue = Field(default_factory=FieldValue)

    def as_line(self) -> str:
        parts = [
            self.street.value or "",
            self.city.value or "",
            self.state.value or "",
            self.zip.value or "",
        ]
        return " ".join(p for p in parts if p).strip()


class ExtractedFields(BaseModel):
    legal_name: FieldValue = Field(default_factory=FieldValue)
    dba_name: FieldValue = Field(default_factory=FieldValue)
    tax_classification: FieldValue = Field(default_factory=FieldValue)
    llc_classification: FieldValue = Field(default_factory=FieldValue)
    foreign_partners_indicator: FieldValue = Field(default_factory=FieldValue)
    exempt_payee_code: FieldValue = Field(default_factory=FieldValue)
    fatca_exemption_code: FieldValue = Field(default_factory=FieldValue)
    address: AddressFields = Field(default_factory=AddressFields)
    account_numbers: FieldValue = Field(default_factory=FieldValue)
    tin: TinValue = Field(default_factory=TinValue)
    signature_present: FieldValue = Field(default_factory=FieldValue)
    signature_date: FieldValue = Field(default_factory=FieldValue)
    signature_name: FieldValue = Field(default_factory=FieldValue)


class DocumentInfo(BaseModel):
    filename: str
    media_type: str
    detected_form: Literal["W-9", "W-8", "UNKNOWN"] = "UNKNOWN"
    form_revision: Optional[str] = None
    page_count: int = 1
    quality_score: float = Field(ge=0.0, le=1.0, default=0.0)
    quality_issues: list[str] = Field(default_factory=list)


class ValidationFlag(BaseModel):
    code: str
    severity: FlagSeverity
    message: str
    field: Optional[str] = None


class ValidationResult(BaseModel):
    passed: bool
    blocking: bool = False
    flags: list[ValidationFlag] = Field(default_factory=list)


class MatchCandidate(BaseModel):
    supplier_id: str
    legal_name: str
    tin_redacted: Optional[str] = None
    tin_match: bool = False
    name_score: float = Field(ge=0.0, le=1.0, default=0.0)
    address_score: float = Field(ge=0.0, le=1.0, default=0.0)
    composite_score: float = Field(ge=0.0, le=1.0, default=0.0)
    status: Optional[str] = None


class MatchResult(BaseModel):
    decision: MatchDecision
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reason_code: str
    reasoning: str
    matched_supplier_id: Optional[str] = None
    material_changes: list[str] = Field(default_factory=list)
    candidates: list[MatchCandidate] = Field(default_factory=list)


class AuditInfo(BaseModel):
    processed_at: datetime
    pipeline_version: str
    schema_version: str = SCHEMA_VERSION
    extractor_path: str
    model_versions: dict[str, str] = Field(default_factory=dict)
    tenant_id: str


class OnboardingResponse(BaseModel):
    """The JSON body a PairSoft product team would persist and act on."""

    request_id: str
    schema_version: str = SCHEMA_VERSION
    document: DocumentInfo
    extraction: ExtractedFields
    overall_confidence: float = Field(ge=0.0, le=1.0)
    validation: ValidationResult
    match: MatchResult
    audit: AuditInfo

    def to_public_dict(self, include_tin: bool = False) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        if not include_tin:
            tin = payload["extraction"]["tin"]
            tin["value"] = None
        return payload


class SupplierRecord(BaseModel):
    """One row from the tenant supplier master."""

    supplier_id: str
    legal_name: str
    dba: Optional[str] = None
    tin: Optional[str] = None
    tin_type: TinType = TinType.UNKNOWN
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    tax_classification: Optional[str] = None
    bank_account_last4: Optional[str] = None
    status: str = "active"
    last_updated: Optional[str] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
