from w9_onboarding.models import (
    AddressFields,
    ExtractedFields,
    FieldSource,
    FieldValue,
    TinType,
    TinValue,
)
from w9_onboarding.validation import validate


def test_unsigned_form_is_error():
    fields = ExtractedFields(
        legal_name=FieldValue(value="ORBITAL PARTS CO", confidence=0.9, source=FieldSource.HEURISTIC),
        tin=TinValue(value="63-9988771", tin_type=TinType.EIN, confidence=0.9, source=FieldSource.HEURISTIC),
        address=AddressFields(
            street=FieldValue(value="16 LAUNCH PAD", confidence=0.9, source=FieldSource.HEURISTIC),
            city=FieldValue(value="HUNTSVILLE", confidence=0.9, source=FieldSource.HEURISTIC),
            state=FieldValue(value="AL", confidence=0.9, source=FieldSource.HEURISTIC),
            zip=FieldValue(value="35801", confidence=0.9, source=FieldSource.HEURISTIC),
        ),
        signature_present=FieldValue(value="false", confidence=0.8, source=FieldSource.HEURISTIC),
    )
    result = validate(fields, "W-9", "2024-March", 0.8, [])
    codes = {flag.code for flag in result.flags}
    assert "MISSING_SIGNATURE" in codes
    assert result.blocking


def test_ssn_on_corporation_is_flagged():
    fields = ExtractedFields(
        legal_name=FieldValue(value="ACME CORPORATION", confidence=0.9, source=FieldSource.HEURISTIC),
        tax_classification=FieldValue(value="C_CORPORATION", confidence=0.9, source=FieldSource.HEURISTIC),
        tin=TinValue(value="456-78-9012", tin_type=TinType.SSN, confidence=0.9, source=FieldSource.HEURISTIC),
        address=AddressFields(
            street=FieldValue(value="100 MARKET STREET", confidence=0.9, source=FieldSource.HEURISTIC),
            city=FieldValue(value="SAN FRANCISCO", confidence=0.9, source=FieldSource.HEURISTIC),
            state=FieldValue(value="CA", confidence=0.9, source=FieldSource.HEURISTIC),
            zip=FieldValue(value="94105", confidence=0.9, source=FieldSource.HEURISTIC),
        ),
        signature_present=FieldValue(value="true", confidence=0.9, source=FieldSource.HEURISTIC),
        signature_date=FieldValue(value="01/01/2026", confidence=0.8, source=FieldSource.HEURISTIC),
    )
    result = validate(fields, "W-9", "2024-March", 0.9, [])
    assert any(flag.code == "TIN_TYPE_CLASSIFICATION_MISMATCH" for flag in result.flags)
