"""Optional LLM refinement over recovered text.

Used only when OPENAI_API_KEY is set. The model never sees an image in
this prototype (cheaper, less PII sprawl). It proposes the same field
shape as the heuristic parser so they can be consensus-merged.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from w9_onboarding.models import (
    AddressFields,
    ExtractedFields,
    FieldSource,
    FieldValue,
    TinType,
    TinValue,
)
from w9_onboarding.security import format_tin, normalize_tin, redact_tin, tin_last4

logger = logging.getLogger(__name__)

SYSTEM = """You extract fields from a US IRS Form W-9. Return JSON only.
If a field is missing, use null. Never invent a TIN.
Schema:
{
  "detected_form": "W-9" | "W-8" | "UNKNOWN",
  "form_revision": string | null,
  "legal_name": string | null,
  "dba_name": string | null,
  "tax_classification": "INDIVIDUAL_SOLE_PROPRIETOR"|"C_CORPORATION"|"S_CORPORATION"|"PARTNERSHIP"|"TRUST_ESTATE"|"LLC"|"OTHER"|null,
  "llc_classification": "C"|"S"|"P"|null,
  "foreign_partners_indicator": "YES"|"NO"|null,
  "exempt_payee_code": string | null,
  "fatca_exemption_code": string | null,
  "street": string | null,
  "city": string | null,
  "state": string | null,
  "zip": string | null,
  "account_numbers": string | null,
  "tin": string | null,
  "tin_type": "EIN"|"SSN"|null,
  "signature_present": true | false | null,
  "signature_name": string | null,
  "signature_date": string | null
}
"""


def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def extract_with_llm(text: str) -> Optional[tuple[ExtractedFields, str, Optional[str], str]]:
    if not llm_available():
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.getenv("W9_LLM_MODEL", "gpt-4o-mini")
    client = OpenAI()
    # Truncate to keep cost predictable; W-9s are short.
    clipped = text[:6000]
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": clipped},
            ],
        )
    except Exception as exc:
        logger.warning("LLM extraction failed: %s", exc)
        return None

    content = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return _to_fields(payload), payload.get("detected_form") or "UNKNOWN", payload.get("form_revision"), model


def _fv(value: object, confidence: float = 0.8) -> FieldValue:
    if value is None or value == "":
        return FieldValue(source=FieldSource.NONE)
    return FieldValue(value=str(value), confidence=confidence, source=FieldSource.LLM)


def _to_fields(payload: dict) -> ExtractedFields:
    tin_raw = payload.get("tin")
    tin_type_raw = payload.get("tin_type") or ""
    digits = normalize_tin(str(tin_raw) if tin_raw else "")
    try:
        tin_type = TinType(str(tin_type_raw).upper()) if tin_type_raw else TinType.UNKNOWN
    except ValueError:
        tin_type = TinType.UNKNOWN
    if tin_type == TinType.UNKNOWN and digits:
        tin_type = TinType.SSN if re.match(r"\d{3}-\d{2}-\d{4}", str(tin_raw)) else TinType.EIN

    tin = TinValue()
    if digits:
        tin = TinValue(
            value=format_tin(digits, tin_type),
            value_redacted=redact_tin(digits, tin_type),
            last4=tin_last4(digits),
            tin_type=tin_type,
            confidence=0.85,
            source=FieldSource.LLM,
        )

    sig_present = payload.get("signature_present")
    if sig_present is True:
        sig_field = FieldValue(value="true", confidence=0.8, source=FieldSource.LLM)
    elif sig_present is False:
        sig_field = FieldValue(value="false", confidence=0.8, source=FieldSource.LLM)
    else:
        sig_field = FieldValue(source=FieldSource.NONE)

    return ExtractedFields(
        legal_name=_fv(payload.get("legal_name")),
        dba_name=_fv(payload.get("dba_name")),
        tax_classification=_fv(payload.get("tax_classification")),
        llc_classification=_fv(payload.get("llc_classification")),
        foreign_partners_indicator=_fv(payload.get("foreign_partners_indicator")),
        exempt_payee_code=_fv(payload.get("exempt_payee_code")),
        fatca_exemption_code=_fv(payload.get("fatca_exemption_code")),
        address=AddressFields(
            street=_fv(payload.get("street")),
            city=_fv(payload.get("city")),
            state=_fv(payload.get("state")),
            zip=_fv(payload.get("zip")),
        ),
        account_numbers=_fv(payload.get("account_numbers")),
        tin=tin,
        signature_present=sig_field,
        signature_date=_fv(payload.get("signature_date")),
        signature_name=_fv(payload.get("signature_name")),
    )
