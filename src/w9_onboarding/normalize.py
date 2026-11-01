"""Shared string normalization for names, addresses, and classifications."""

from __future__ import annotations

import re
from typing import Optional

_PUNCT = re.compile(r"[.,'/&#()]+")
_WS = re.compile(r"\s+")

_LEGAL_SUFFIXES = (
    r"\bINCORPORATED\b",
    r"\bCORPORATION\b",
    r"\bCOMPANY\b",
    r"\bLIMITED\b",
    r"\bCORP\b",
    r"\bINC\b",
    r"\bLLC\b",
    r"\bLTD\b",
    r"\bLP\b",
    r"\bLLP\b",
    r"\bPC\b",
    r"\bPLLC\b",
    r"\bCO\b",
)

_SUFFIX_RE = re.compile("|".join(_LEGAL_SUFFIXES))
_THE_RE = re.compile(r"^THE\s+")


def collapse_ws(value: Optional[str]) -> str:
    if not value:
        return ""
    return _WS.sub(" ", value).strip()


def normalize_name(value: Optional[str]) -> str:
    """Aggressive legal-name fold used for matching, not for display."""
    text = collapse_ws(value).upper()
    if not text:
        return ""
    text = _PUNCT.sub(" ", text)
    text = _THE_RE.sub("", text)
    text = _SUFFIX_RE.sub(" ", text)
    return collapse_ws(text)


def names_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    return normalize_name(a) == normalize_name(b) and bool(normalize_name(a))


def normalize_state(value: Optional[str]) -> str:
    text = collapse_ws(value).upper()
    aliases = {
        "CALIFORNIA": "CA",
        "NEW YORK": "NY",
        "TEXAS": "TX",
        "WASHINGTON": "WA",
        "ILLINOIS": "IL",
        "NEW JERSEY": "NJ",
        "FLORIDA": "FL",
    }
    return aliases.get(text, text)


def normalize_zip(value: Optional[str]) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    return digits[:5]


def normalize_street(value: Optional[str]) -> str:
    text = collapse_ws(value).upper()
    replacements = {
        r"\bSTREET\b": "ST",
        r"\bAVENUE\b": "AVE",
        r"\bBOULEVARD\b": "BLVD",
        r"\bDRIVE\b": "DR",
        r"\bROAD\b": "RD",
        r"\bSUITE\b": "STE",
        r"\bFLOOR\b": "FL",
        r"\bNORTH\b": "N",
        r"\bSOUTH\b": "S",
        r"\bEAST\b": "E",
        r"\bWEST\b": "W",
    }
    text = _PUNCT.sub(" ", text)
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)
    return collapse_ws(text)


CLASSIFICATION_ALIASES = {
    "INDIVIDUAL": "INDIVIDUAL_SOLE_PROPRIETOR",
    "INDIVIDUAL/SOLE PROPRIETOR": "INDIVIDUAL_SOLE_PROPRIETOR",
    "SOLE PROPRIETOR": "INDIVIDUAL_SOLE_PROPRIETOR",
    "SOLE PROPRIETORSHIP": "INDIVIDUAL_SOLE_PROPRIETOR",
    "C CORPORATION": "C_CORPORATION",
    "C CORP": "C_CORPORATION",
    "C_CORPORATION": "C_CORPORATION",
    "S CORPORATION": "S_CORPORATION",
    "S CORP": "S_CORPORATION",
    "S_CORPORATION": "S_CORPORATION",
    "PARTNERSHIP": "PARTNERSHIP",
    "TRUST": "TRUST_ESTATE",
    "TRUST/ESTATE": "TRUST_ESTATE",
    "TRUST_ESTATE": "TRUST_ESTATE",
    "ESTATE": "TRUST_ESTATE",
    "LLC": "LLC",
    "LIMITED LIABILITY COMPANY": "LLC",
    "OTHER": "OTHER",
}


def normalize_classification(value: Optional[str]) -> str:
    if not value:
        return "UNKNOWN"
    key = collapse_ws(value).upper().replace("_", " ").replace("-", " ")
    key = re.sub(r"\s+", " ", key)
    compact = key.replace(" ", "_")
    if compact in CLASSIFICATION_ALIASES:
        return CLASSIFICATION_ALIASES[compact]
    if key in CLASSIFICATION_ALIASES:
        return CLASSIFICATION_ALIASES[key]
    for alias, canonical in CLASSIFICATION_ALIASES.items():
        if alias in key:
            return canonical
    return "UNKNOWN"
