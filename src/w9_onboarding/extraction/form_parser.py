"""Heuristic W-9 parser.

Opinion: a labeled-form parser is the right local default. Real W-9s are
a known layout family, not free text. Production replaces this module
with Azure Document Intelligence custom fields and keeps the same
ExtractedFields shape.
"""

from __future__ import annotations

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
from w9_onboarding.normalize import collapse_ws, normalize_classification, normalize_state
from w9_onboarding.security import (
    detect_tin_type,
    format_tin,
    looks_like_ein_format,
    looks_like_ssn_format,
    normalize_tin,
    redact_tin,
    tin_last4,
)

CLASS_PATTERNS = [
    (r"individual/?\s*sole\s*proprietor", "INDIVIDUAL_SOLE_PROPRIETOR"),
    (r"\bc\s*corporation\b", "C_CORPORATION"),
    (r"\bs\s*corporation\b", "S_CORPORATION"),
    (r"\bpartnership\b", "PARTNERSHIP"),
    (r"trust/?\s*estate", "TRUST_ESTATE"),
    (r"\bllc\b", "LLC"),
    (r"\bother\b", "OTHER"),
]


def parse_w9_text(text: str) -> tuple[ExtractedFields, str, Optional[str], str]:
    """Return fields, detected form, revision, and extractor path label."""
    detected = _detect_form(text)
    revision = _detect_revision(text)
    fields = ExtractedFields()
    if detected != "W-9":
        return fields, detected, revision, "heuristic"

    fields.legal_name = _field(
        _first_labeled(
            text,
            [
                r"line\s*1\s*name",
                r"name\s*\(as shown on your income tax return\)",
                r"legal name",
                r"name as shown on your income tax return",
            ],
        ),
        0.9,
    )
    fields.dba_name = _field(
        _first_labeled(
            text,
            [
                r"line\s*2\s*(?:business name|dba)",
                r"business name/?disregarded entity name",
                r"business name",
                r"dba",
            ],
        ),
        0.82,
    )

    classification, llc_letter, class_conf = _parse_classification(text)
    fields.tax_classification = _field(classification, class_conf)
    fields.llc_classification = _field(llc_letter, 0.8 if llc_letter else 0.0)

    fields.foreign_partners_indicator = _field(_yes_no(text, r"foreign\s+partners?"), 0.6)
    fields.exempt_payee_code = _field(
        _first_labeled(text, [r"exempt payee code", r"line\s*4\s*exempt payee"]),
        0.7,
    )
    fields.fatca_exemption_code = _field(
        _first_labeled(text, [r"fatca\s+exemption", r"exemption from fatca"]),
        0.7,
    )

    street = _first_labeled(
        text,
        [r"line\s*5\s*address", r"address\s*\(number, street", r"^address"],
    )
    city_line = _first_labeled(
        text,
        [r"line\s*6\s*city", r"city,\s*state,\s*and zip", r"city/state/zip", r"city, state, zip"],
    )
    fields.address = _parse_address(street, city_line, text)

    fields.account_numbers = _field(
        _first_labeled(text, [r"line\s*7", r"account number"]),
        0.65,
    )

    fields.tin = _parse_tin(text)
    sig_name, sig_date, signed = _parse_signature(text)
    fields.signature_name = _field(sig_name, 0.75 if sig_name else 0.0)
    fields.signature_date = _field(sig_date, 0.8 if sig_date else 0.0)
    fields.signature_present = FieldValue(
        value="true" if signed else "false",
        confidence=0.85 if signed else 0.8,
        source=FieldSource.HEURISTIC,
    )
    return fields, detected, revision, "heuristic"


def _detect_form(text: str) -> str:
    upper = text.upper()
    if re.search(r"FORM\s*W-?8", upper):
        return "W-8"
    if re.search(r"FORM\s*W-?9", upper) or "TAXPAYER IDENTIFICATION NUMBER AND CERTIFICATION" in upper:
        return "W-9"
    return "UNKNOWN"


def _detect_revision(text: str) -> Optional[str]:
    match = re.search(
        r"(?:Rev(?:ised|\.)?\s*)(?:(January|March|October|December)[,\s]+)?(20\d{2})(?:-([A-Za-z]+))?",
        text,
        re.I,
    )
    if match:
        month = (match.group(1) or match.group(3) or "").title()
        year = match.group(2)
        return f"{year}-{month}" if month else year
    year = re.search(r"\b(201[78]|202[0-6])\b", text)
    return year.group(1) if year else None


def _field(value: Optional[str], confidence: float) -> FieldValue:
    cleaned = collapse_ws(value)
    if not cleaned or cleaned.upper() in {"N/A", "NONE", "BLANK", "-"}:
        return FieldValue(value=None, confidence=0.0, source=FieldSource.NONE)
    return FieldValue(value=cleaned, confidence=confidence, source=FieldSource.HEURISTIC)


def _first_labeled(text: str, labels: list[str]) -> Optional[str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for label in labels:
            match = re.match(rf"(?i){label}\b[^:]*:\s*(.+)$", line)
            if match:
                return _clean_value(match.group(1))
    # Fallback: search anywhere in a line, then take the remainder.
    for raw_line in text.splitlines():
        line = raw_line.strip()
        for label in labels:
            match = re.search(rf"(?i){label}\b[^:]*:\s*(.+)$", line)
            if match:
                return _clean_value(match.group(1))
    # Two-line: label then following non-empty line.
    lines = [ln.strip() for ln in text.splitlines()]
    for idx, line in enumerate(lines):
        for label in labels:
            if re.search(rf"(?i)^{label}\s*[:\-]?\s*$", line) and idx + 1 < len(lines):
                nxt = lines[idx + 1]
                if nxt and not _looks_like_label(nxt):
                    return _clean_value(nxt)
    return None


def _looks_like_label(line: str) -> bool:
    return bool(
        re.match(
            r"(?i)^(line\s*\d|part\s+[iv]+|name|address|city|federal tax|signature|date|ein|ssn|tin)\b",
            line,
        )
    )


def _clean_value(value: str) -> str:
    value = collapse_ws(value)
    value = re.sub(r"^[:\-]\s*", "", value)
    return value.strip(" .")


def _parse_classification(text: str) -> tuple[Optional[str], Optional[str], float]:
    marked = re.findall(
        r"(?im)(?:\[(?:x|X|yes)\]|\bchecked\b)\s*[:\-]?\s*([A-Za-z /]+)",
        text,
    )
    for token in marked:
        normalized = normalize_classification(token)
        if normalized != "UNKNOWN":
            llc = _llc_letter(text) if normalized == "LLC" else None
            return normalized, llc, 0.92

    # Explicit "Federal tax classification: C Corporation"
    labeled = _first_labeled(
        text,
        [
            r"line\s*3a?\s*federal tax classification",
            r"federal tax classification",
            r"tax classification",
        ],
    )
    if labeled:
        normalized = normalize_classification(labeled)
        if normalized != "UNKNOWN":
            llc = _llc_letter(labeled + "\n" + text) if normalized == "LLC" else None
            return normalized, llc, 0.9

    # Last resort: first classification keyword in the document body.
    for pattern, canonical in CLASS_PATTERNS:
        if re.search(pattern, text, re.I):
            llc = _llc_letter(text) if canonical == "LLC" else None
            return canonical, llc, 0.55
    return None, None, 0.0


def _llc_letter(text: str) -> Optional[str]:
    match = re.search(r"(?i)llc(?:\s+classification)?\s*[:\-]?\s*([CSP])\b", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"(?i)\bclassified as\s+([CSP])\b", text)
    return match.group(1).upper() if match else None


def _yes_no(text: str, pattern: str) -> Optional[str]:
    match = re.search(rf"(?i){pattern}[^.\n]{{0,40}}(yes|no)", text)
    return match.group(1).upper() if match else None


def _parse_address(street: Optional[str], city_line: Optional[str], text: str) -> AddressFields:
    address = AddressFields()
    if street:
        address.street = _field(street, 0.9)
    city = state = zip_code = None
    if city_line:
        city, state, zip_code = _split_city_state_zip(city_line)
    if not (city and state):
        fallback = re.search(
            r"(?im)(?:city,?\s*state,?\s*(?:and\s*)?zip(?:\s*code)?\s*[:\-]\s*)?([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
            text,
        )
        if fallback:
            city = city or fallback.group(1)
            state = state or fallback.group(2)
            zip_code = zip_code or fallback.group(3)
    if city:
        address.city = _field(city, 0.9)
    if state:
        address.state = _field(normalize_state(state), 0.93)
    if zip_code:
        address.zip = _field(zip_code, 0.93)
    return address


def _split_city_state_zip(line: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    match = re.search(
        r"^\s*([A-Za-z .'-]+),\s*([A-Za-z]{2}|[A-Za-z]+)\s+(\d{5}(?:-\d{4})?)\s*$",
        line,
    )
    if not match:
        return None, None, None
    return collapse_ws(match.group(1)), normalize_state(match.group(2)), match.group(3)


def _parse_tin(text: str) -> TinValue:
    ein_labeled = re.search(
        r"(?is)(employer identification number|ein)\s*[:\-]?\s*(\d{2}[-\s]?\d{7})",
        text,
    )
    ssn_labeled = re.search(
        r"(?is)(social security number|ssn)\s*[:\-]?\s*(\d{3}[-\s]?\d{2}[-\s]?\d{4})",
        text,
    )
    generic = re.search(
        r"(?is)(?:taxpayer identification number|\btin\b)\s*[:\-]?\s*(\d{2,3}[-\s]?\d{2,7}(?:[-\s]?\d{4})?)",
        text,
    )

    chosen_raw = None
    hint = None
    confidence = 0.0
    if ein_labeled:
        chosen_raw, hint, confidence = ein_labeled.group(2), "EIN", 0.95
    elif ssn_labeled:
        chosen_raw, hint, confidence = ssn_labeled.group(2), "SSN", 0.95
    elif generic:
        chosen_raw, hint, confidence = generic.group(1), generic.group(0), 0.75
    else:
        # Last resort: any 9-digit token that looks like a TIN.
        loose = re.search(r"\b(\d{2}-\d{7}|\d{3}-\d{2}-\d{4})\b", text)
        if loose:
            chosen_raw, hint, confidence = loose.group(1), None, 0.5

    digits = normalize_tin(chosen_raw)
    tin_type = detect_tin_type(digits, hint)
    if tin_type == TinType.UNKNOWN and digits:
        if "-" in (chosen_raw or "") and re.match(r"\d{3}-\d{2}-\d{4}", chosen_raw or ""):
            tin_type = TinType.SSN
        elif "-" in (chosen_raw or "") and re.match(r"\d{2}-\d{7}", chosen_raw or ""):
            tin_type = TinType.EIN
        elif looks_like_ssn_format(digits) and not looks_like_ein_format(digits):
            tin_type = TinType.SSN
        elif digits:
            # Prefer EIN for business-looking forms, SSN only when labeled.
            tin_type = TinType.EIN if not ssn_labeled else TinType.SSN

    if not digits:
        return TinValue()
    return TinValue(
        value=format_tin(digits, tin_type),
        value_redacted=redact_tin(digits, tin_type),
        last4=tin_last4(digits),
        tin_type=tin_type,
        confidence=confidence,
        source=FieldSource.HEURISTIC,
    )


def _parse_signature(text: str) -> tuple[Optional[str], Optional[str], bool]:
    sig = _first_labeled(text, [r"signature(?:\s+of\s+u\.?s\.?\s+person)?", r"signed by"])
    date = _first_labeled(text, [r"date", r"signature date"])
    signed = False
    if sig and not re.search(r"(?i)\b(none|n/a|missing|unsigned)\b", sig):
        signed = True
    if re.search(r"(?i)signature\s*[:\-]\s*(present|signed|yes)", text):
        signed = True
        sig = sig or "signed"
    if re.search(r"(?i)signature\s*(missing|not present|unsigned)", text):
        signed = False
        sig = None
    return sig, date, signed
