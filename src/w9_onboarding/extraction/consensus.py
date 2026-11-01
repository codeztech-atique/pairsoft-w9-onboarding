"""Merge heuristic and LLM extractions into one field set.

Agreement raises confidence. Disagreement keeps the stronger value and
lowers confidence so matching will not auto-act on a fight between
extractors.
"""

from __future__ import annotations

from typing import Optional

from rapidfuzz import fuzz

from w9_onboarding.models import (
    AddressFields,
    ExtractedFields,
    FieldSource,
    FieldValue,
    TinValue,
)
from w9_onboarding.normalize import normalize_name
from w9_onboarding.security import normalize_tin


def merge_extractions(
    heuristic: ExtractedFields,
    llm: Optional[ExtractedFields],
) -> tuple[ExtractedFields, list[str]]:
    if llm is None:
        return heuristic, []

    disagreements: list[str] = []
    merged = ExtractedFields(
        legal_name=_merge_text("legal_name", heuristic.legal_name, llm.legal_name, disagreements, name_like=True),
        dba_name=_merge_text("dba_name", heuristic.dba_name, llm.dba_name, disagreements, name_like=True),
        tax_classification=_merge_text(
            "tax_classification", heuristic.tax_classification, llm.tax_classification, disagreements
        ),
        llc_classification=_merge_text(
            "llc_classification", heuristic.llc_classification, llm.llc_classification, disagreements
        ),
        foreign_partners_indicator=_merge_text(
            "foreign_partners_indicator",
            heuristic.foreign_partners_indicator,
            llm.foreign_partners_indicator,
            disagreements,
        ),
        exempt_payee_code=_merge_text(
            "exempt_payee_code", heuristic.exempt_payee_code, llm.exempt_payee_code, disagreements
        ),
        fatca_exemption_code=_merge_text(
            "fatca_exemption_code", heuristic.fatca_exemption_code, llm.fatca_exemption_code, disagreements
        ),
        address=AddressFields(
            street=_merge_text("street", heuristic.address.street, llm.address.street, disagreements),
            city=_merge_text("city", heuristic.address.city, llm.address.city, disagreements),
            state=_merge_text("state", heuristic.address.state, llm.address.state, disagreements),
            zip=_merge_text("zip", heuristic.address.zip, llm.address.zip, disagreements),
        ),
        account_numbers=_merge_text(
            "account_numbers", heuristic.account_numbers, llm.account_numbers, disagreements
        ),
        tin=_merge_tin(heuristic.tin, llm.tin, disagreements),
        signature_present=_merge_text(
            "signature_present", heuristic.signature_present, llm.signature_present, disagreements
        ),
        signature_date=_merge_text(
            "signature_date", heuristic.signature_date, llm.signature_date, disagreements
        ),
        signature_name=_merge_text(
            "signature_name", heuristic.signature_name, llm.signature_name, disagreements
        ),
    )
    return merged, disagreements


def _merge_text(
    field: str,
    left: FieldValue,
    right: FieldValue,
    disagreements: list[str],
    name_like: bool = False,
) -> FieldValue:
    if left.filled() and not right.filled():
        return left
    if right.filled() and not left.filled():
        return right
    if not left.filled() and not right.filled():
        return FieldValue()

    similar = _similar(left.value, right.value, name_like=name_like)
    winner = left if left.confidence >= right.confidence else right
    if similar:
        return FieldValue(
            value=winner.value,
            confidence=min(1.0, max(left.confidence, right.confidence) + 0.08),
            source=FieldSource.CONSENSUS,
        )
    disagreements.append(field)
    return FieldValue(
        value=winner.value,
        confidence=min(left.confidence, right.confidence) * 0.7,
        source=winner.source,
    )


def _merge_tin(left: TinValue, right: TinValue, disagreements: list[str]) -> TinValue:
    left_digits = normalize_tin(left.value)
    right_digits = normalize_tin(right.value)
    if left_digits and not right_digits:
        return left
    if right_digits and not left_digits:
        return right
    if not left_digits and not right_digits:
        return TinValue()
    if left_digits == right_digits:
        winner = left if left.confidence >= right.confidence else right
        winner.confidence = min(1.0, max(left.confidence, right.confidence) + 0.05)
        winner.source = FieldSource.CONSENSUS
        return winner
    disagreements.append("tin")
    winner = left if left.confidence >= right.confidence else right
    winner.confidence = min(left.confidence, right.confidence) * 0.6
    return winner


def _similar(a: Optional[str], b: Optional[str], name_like: bool) -> bool:
    if not a or not b:
        return False
    if a.strip().upper() == b.strip().upper():
        return True
    if name_like:
        return fuzz.token_sort_ratio(normalize_name(a), normalize_name(b)) >= 90
    return fuzz.ratio(a.strip().upper(), b.strip().upper()) >= 90
