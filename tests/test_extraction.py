from w9_onboarding.extraction.form_parser import parse_w9_text


SAMPLE = """
Form W-9  (Rev. March 2024)
Request for Taxpayer Identification Number and Certification
Line 1 Name (as shown on your income tax return): ACME CORPORATION
Line 2 Business name/disregarded entity name: ACME
Line 3 Federal tax classification: [X] C Corporation
Line 5 Address (number, street, and apt. or suite no.): 100 MARKET STREET
Line 6 City, state, and ZIP code: SAN FRANCISCO, CA 94105
Employer identification number: 12-3456789
Signature of U.S. person: J. SMITH
Date: 01/12/2026
"""


def test_parser_reads_core_w9_fields():
    fields, detected, revision, _ = parse_w9_text(SAMPLE)
    assert detected == "W-9"
    assert revision == "2024-March"
    assert fields.legal_name.value == "ACME CORPORATION"
    assert fields.dba_name.value == "ACME"
    assert fields.tax_classification.value == "C_CORPORATION"
    assert fields.address.street.value == "100 MARKET STREET"
    assert fields.address.city.value == "SAN FRANCISCO"
    assert fields.address.state.value == "CA"
    assert fields.address.zip.value == "94105"
    assert fields.tin.value == "12-3456789"
    assert fields.tin.tin_type.value == "EIN"
    assert fields.tin.value_redacted == "**-***6789"
    assert fields.signature_present.value == "true"


def test_parser_detects_w8():
    fields, detected, _, _ = parse_w9_text("Form W-8BEN Certificate of Foreign Status")
    assert detected == "W-8"
    assert fields.legal_name.value is None
