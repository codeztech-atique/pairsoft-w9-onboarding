"""Load a tenant supplier master from CSV or JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from w9_onboarding.models import SupplierRecord, TinType
from w9_onboarding.security import detect_tin_type, normalize_tin


def load_supplier_master(path: str | Path) -> list[SupplierRecord]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Supplier master not found: {path}")
    if path.suffix.lower() == ".json":
        return _from_json(path)
    return _from_csv(path)


def _from_csv(path: Path) -> list[SupplierRecord]:
    records: list[SupplierRecord] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            records.append(_row_to_record(row))
    return records


def _from_json(path: Path) -> list[SupplierRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "suppliers" in payload:
        payload = payload["suppliers"]
    return [_row_to_record(row) for row in payload]


def _row_to_record(row: dict) -> SupplierRecord:
    tin_raw = row.get("tin") or row.get("TIN") or ""
    digits = normalize_tin(tin_raw)
    hinted = row.get("tin_type") or row.get("tinType") or ""
    tin_type = detect_tin_type(digits, hinted)
    if tin_type == TinType.UNKNOWN and hinted:
        try:
            tin_type = TinType(str(hinted).upper())
        except ValueError:
            tin_type = TinType.UNKNOWN
    return SupplierRecord(
        supplier_id=str(row.get("supplier_id") or row.get("id") or "").strip(),
        legal_name=str(row.get("legal_name") or row.get("name") or "").strip(),
        dba=(row.get("dba") or None),
        tin=digits or None,
        tin_type=tin_type,
        street=row.get("street") or None,
        city=row.get("city") or None,
        state=row.get("state") or None,
        zip=row.get("zip") or row.get("zip_code") or None,
        tax_classification=row.get("tax_classification") or None,
        bank_account_last4=row.get("bank_account_last4") or None,
        status=str(row.get("status") or "active"),
        last_updated=row.get("last_updated") or None,
    )
