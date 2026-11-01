from w9_onboarding.matching import match_supplier
from w9_onboarding.models import (
    AddressFields,
    ExtractedFields,
    FieldSource,
    FieldValue,
    MatchDecision,
    SupplierRecord,
    TinType,
    TinValue,
    ValidationResult,
)
from w9_onboarding.security import format_tin, redact_tin


def _fields(**kwargs) -> ExtractedFields:
    tin_digits = kwargs.pop("tin", "123456789")
    tin_type = TinType(kwargs.pop("tin_type", "EIN"))
    address = AddressFields(
        street=FieldValue(value=kwargs.pop("street", "100 MARKET STREET"), confidence=0.9, source=FieldSource.HEURISTIC),
        city=FieldValue(value=kwargs.pop("city", "SAN FRANCISCO"), confidence=0.9, source=FieldSource.HEURISTIC),
        state=FieldValue(value=kwargs.pop("state", "CA"), confidence=0.9, source=FieldSource.HEURISTIC),
        zip=FieldValue(value=kwargs.pop("zip", "94105"), confidence=0.9, source=FieldSource.HEURISTIC),
    )
    return ExtractedFields(
        legal_name=FieldValue(value=kwargs.pop("legal_name", "ACME CORPORATION"), confidence=0.9, source=FieldSource.HEURISTIC),
        dba_name=FieldValue(value=kwargs.pop("dba_name", "ACME"), confidence=0.8, source=FieldSource.HEURISTIC),
        tax_classification=FieldValue(value=kwargs.pop("tax_classification", "C_CORPORATION"), confidence=0.9, source=FieldSource.HEURISTIC),
        address=address,
        tin=TinValue(
            value=format_tin(tin_digits, tin_type),
            value_redacted=redact_tin(tin_digits, tin_type),
            last4=tin_digits[-4:],
            tin_type=tin_type,
            confidence=0.95,
            source=FieldSource.HEURISTIC,
        ),
        signature_present=FieldValue(value="true", confidence=0.9, source=FieldSource.HEURISTIC),
    )


def _acme() -> SupplierRecord:
    return SupplierRecord(
        supplier_id="SUP-1001",
        legal_name="ACME CORPORATION",
        dba="ACME",
        tin="123456789",
        tin_type=TinType.EIN,
        street="100 MARKET STREET",
        city="SAN FRANCISCO",
        state="CA",
        zip="94105",
        tax_classification="C_CORPORATION",
        status="active",
    )


def test_exact_tin_and_name_updates():
    result = match_supplier(_fields(), [_acme()], ValidationResult(passed=True), 0.9, "W-9")
    assert result.decision == MatchDecision.UPDATE_EXISTING
    assert result.reason_code == "EXACT_TIN_AND_NAME"
    assert result.matched_supplier_id == "SUP-1001"


def test_material_address_change_reviews():
    result = match_supplier(
        _fields(street="200 MARKET STREET", zip="94107"),
        [_acme()],
        ValidationResult(passed=True),
        0.9,
        "W-9",
    )
    assert result.decision == MatchDecision.HUMAN_REVIEW
    assert result.reason_code == "MATERIAL_CHANGE"
    assert "address" in result.material_changes


def test_tin_name_conflict_reviews():
    result = match_supplier(
        _fields(legal_name="NORTHWIND TRADING LLC", dba_name="NORTHWIND"),
        [_acme()],
        ValidationResult(passed=True),
        0.9,
        "W-9",
    )
    assert result.decision == MatchDecision.HUMAN_REVIEW
    assert result.reason_code == "TIN_NAME_CONFLICT"


def test_unknown_supplier_creates():
    result = match_supplier(
        _fields(
            legal_name="HOSU LOGISTICS INC",
            dba_name=None,
            tin="842211099",
            street="740 MISSION ROAD",
            city="DENVER",
            state="CO",
            zip="80202",
        ),
        [_acme()],
        ValidationResult(passed=True),
        0.9,
        "W-9",
    )
    assert result.decision == MatchDecision.CREATE_NEW
    assert result.reason_code == "NO_MATCH"


def test_wrong_form_reviews():
    result = match_supplier(_fields(), [_acme()], ValidationResult(passed=False), 0.9, "W-8")
    assert result.decision == MatchDecision.HUMAN_REVIEW
    assert result.reason_code == "WRONG_FORM"
