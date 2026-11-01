"""Lightweight evaluation against golden labels.

This is the quality signal I would grow into a regression suite:
field-level extraction accuracy plus decision-level matching accuracy.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from rapidfuzz import fuzz

from w9_onboarding.master import load_supplier_master
from w9_onboarding.normalize import normalize_classification, normalize_name
from w9_onboarding.pipeline import process_document
from w9_onboarding.samples import generate_fixtures
from w9_onboarding.security import normalize_tin


@dataclass
class CaseResult:
    filename: str
    expected_decision: str
    actual_decision: str
    decision_ok: bool
    expected_reason: str
    actual_reason: str
    reason_ok: bool
    field_hits: int
    field_total: int
    notes: str


def evaluate(
    data_dir: Path,
    use_llm: bool = False,
    regenerate: bool = True,
) -> dict:
    if regenerate or not (data_dir / "samples").exists():
        generate_fixtures(data_dir.parent if data_dir.name == "data" else data_dir)
        data_dir = data_dir if data_dir.name == "data" else data_dir / "data"

    golden_path = data_dir / "golden" / "labels.json"
    master_path = data_dir / "supplier_master.csv"
    samples_dir = data_dir / "samples"
    labels = json.loads(golden_path.read_text(encoding="utf-8"))
    master = load_supplier_master(master_path)

    cases: list[CaseResult] = []
    for label in labels:
        path = samples_dir / label["filename"]
        result = process_document(path, master, use_llm=use_llm)
        field_hits, field_total = _field_score(label, result.extraction, result.document.detected_form)
        cases.append(
            CaseResult(
                filename=label["filename"],
                expected_decision=label["expected_decision"],
                actual_decision=result.match.decision.value,
                decision_ok=result.match.decision.value == label["expected_decision"],
                expected_reason=label["expected_reason"],
                actual_reason=result.match.reason_code,
                reason_ok=result.match.reason_code == label["expected_reason"],
                field_hits=field_hits,
                field_total=field_total,
                notes=label.get("notes") or "",
            )
        )

    decision_acc = _rate([c.decision_ok for c in cases])
    reason_acc = _rate([c.reason_ok for c in cases])
    field_acc = _rate_counts(sum(c.field_hits for c in cases), sum(c.field_total for c in cases))
    return {
        "cases": [asdict(c) for c in cases],
        "metrics": {
            "n_cases": len(cases),
            "decision_accuracy": decision_acc,
            "reason_accuracy": reason_acc,
            "field_accuracy": field_acc,
        },
    }


def _field_score(label: dict, extraction, detected_form: str) -> tuple[int, int]:
    if label["form"] != "W-9":
        return (1, 1) if detected_form == "W-8" else (0, 1)

    checks = []
    checks.append(_name_ok(label.get("legal_name"), extraction.legal_name.value))
    if label.get("dba_name"):
        checks.append(_name_ok(label["dba_name"], extraction.dba_name.value))
    if label.get("tax_classification"):
        checks.append(
            normalize_classification(extraction.tax_classification.value)
            == normalize_classification(label["tax_classification"])
        )
    checks.append(normalize_tin(extraction.tin.value) == normalize_tin(label.get("tin")))
    if label.get("street"):
        checks.append(
            fuzz.token_sort_ratio(
                (extraction.address.street.value or "").upper(),
                label["street"].upper(),
            )
            >= 90
        )
    if label.get("city"):
        checks.append((extraction.address.city.value or "").upper() == label["city"].upper())
    if label.get("state"):
        checks.append((extraction.address.state.value or "").upper() == label["state"].upper())
    if label.get("zip"):
        checks.append((extraction.address.zip.value or "")[:5] == label["zip"][:5])
    expected_signed = "true" if label.get("signed") else "false"
    checks.append(extraction.signature_present.value == expected_signed)
    return sum(1 for item in checks if item), len(checks)


def _name_ok(expected: str | None, actual: str | None) -> bool:
    if not expected:
        return not actual
    if not actual:
        return False
    if normalize_name(expected) == normalize_name(actual):
        return True
    return fuzz.token_sort_ratio(expected, actual) >= 90


def _rate(flags: list[bool]) -> float:
    if not flags:
        return 0.0
    return round(sum(1 for flag in flags if flag) / len(flags), 3)


def _rate_counts(hits: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(hits / total, 3)
