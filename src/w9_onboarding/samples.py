"""Deterministic sample W-9 PDFs, supplier master, and golden labels."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
GOLDEN_PATH = DATA_DIR / "golden" / "labels.json"
MASTER_PATH = DATA_DIR / "supplier_master.csv"

SUPPLIERS = [
    {
        "supplier_id": "SUP-1001",
        "legal_name": "ACME CORPORATION",
        "dba": "ACME",
        "tin": "123456789",
        "tin_type": "EIN",
        "street": "100 MARKET STREET",
        "city": "SAN FRANCISCO",
        "state": "CA",
        "zip": "94105",
        "tax_classification": "C_CORPORATION",
        "bank_account_last4": "4421",
        "status": "active",
        "last_updated": "2024-01-15",
    },
    {
        "supplier_id": "SUP-1002",
        "legal_name": "GLOBEX CORP INC",
        "dba": "GLOBEX",
        "tin": "987654321",
        "tin_type": "EIN",
        "street": "500 PARK AVENUE",
        "city": "NEW YORK",
        "state": "NY",
        "zip": "10022",
        "tax_classification": "C_CORPORATION",
        "bank_account_last4": "1002",
        "status": "active",
        "last_updated": "2025-03-01",
    },
    {
        "supplier_id": "SUP-1003",
        "legal_name": "JANE A SMITH",
        "dba": "SMITH CONSULTING",
        "tin": "456789012",
        "tin_type": "SSN",
        "street": "88 PINE STREET",
        "city": "SEATTLE",
        "state": "WA",
        "zip": "98101",
        "tax_classification": "INDIVIDUAL_SOLE_PROPRIETOR",
        "bank_account_last4": "7788",
        "status": "active",
        "last_updated": "2023-11-02",
    },
    {
        "supplier_id": "SUP-1004",
        "legal_name": "INITECH LLC",
        "dba": "",
        "tin": "112233445",
        "tin_type": "EIN",
        "street": "42 OFFICE PARK",
        "city": "AUSTIN",
        "state": "TX",
        "zip": "78701",
        "tax_classification": "LLC",
        "bank_account_last4": "0007",
        "status": "active",
        "last_updated": "2024-08-20",
    },
    {
        "supplier_id": "SUP-1005",
        "legal_name": "UMBRELLA INDUSTRIES",
        "dba": "",
        "tin": "556677889",
        "tin_type": "EIN",
        "street": "1 RACCOON CITY RD",
        "city": "CHICAGO",
        "state": "IL",
        "zip": "60601",
        "tax_classification": "C_CORPORATION",
        "bank_account_last4": "1919",
        "status": "inactive",
        "last_updated": "2022-02-02",
    },
    {
        "supplier_id": "SUP-1006",
        "legal_name": "STARK INDUSTRIES",
        "dba": "",
        "tin": "102938475",
        "tin_type": "EIN",
        "street": "200 PARK PLACE",
        "city": "MALIBU",
        "state": "CA",
        "zip": "90265",
        "tax_classification": "C_CORPORATION",
        "bank_account_last4": "3000",
        "status": "active",
        "last_updated": "2025-01-10",
    },
    {
        "supplier_id": "SUP-1007",
        "legal_name": "WAYNE ENTERPRISES",
        "dba": "",
        "tin": "564738291",
        "tin_type": "EIN",
        "street": "1007 MOUNTAIN DRIVE",
        "city": "GOTHAM",
        "state": "NJ",
        "zip": "07001",
        "tax_classification": "C_CORPORATION",
        "bank_account_last4": "1989",
        "status": "active",
        "last_updated": "2024-12-01",
    },
    {
        "supplier_id": "SUP-1008",
        "legal_name": "PIERCE & PIERCE",
        "dba": "",
        "tin": "334455667",
        "tin_type": "EIN",
        "street": "55 WALL STREET",
        "city": "NEW YORK",
        "state": "NY",
        "zip": "10005",
        "tax_classification": "PARTNERSHIP",
        "bank_account_last4": "1987",
        "status": "active",
        "last_updated": "2025-06-01",
    },
]


# Each sample is the extraction truth plus the expected match decision.
SAMPLES = [
    {
        "filename": "w9_acme_resubmit.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "ACME CORPORATION",
        "dba_name": "ACME",
        "tax_classification": "C_CORPORATION",
        "llc_classification": None,
        "street": "100 MARKET STREET",
        "city": "SAN FRANCISCO",
        "state": "CA",
        "zip": "94105",
        "tin": "12-3456789",
        "tin_type": "EIN",
        "signature_name": "J. SMITH",
        "signature_date": "01/12/2026",
        "signed": True,
        "expected_decision": "UPDATE_EXISTING",
        "expected_reason": "EXACT_TIN_AND_NAME",
        "expected_supplier_id": "SUP-1001",
        "notes": "Clean resubmission of an existing supplier. No material change.",
    },
    {
        "filename": "w9_acme_moved.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "ACME CORPORATION",
        "dba_name": "ACME",
        "tax_classification": "C_CORPORATION",
        "llc_classification": None,
        "street": "200 MARKET STREET STE 400",
        "city": "SAN FRANCISCO",
        "state": "CA",
        "zip": "94107",
        "tin": "12-3456789",
        "tin_type": "EIN",
        "signature_name": "J. SMITH",
        "signature_date": "03/02/2026",
        "signed": True,
        "expected_decision": "HUMAN_REVIEW",
        "expected_reason": "MATERIAL_CHANGE",
        "expected_supplier_id": "SUP-1001",
        "notes": "Same legal identity, new address. Pay-to change needs review.",
    },
    {
        "filename": "w9_acme_name_variant.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "ACME CORP.",
        "dba_name": "ACME",
        "tax_classification": "C_CORPORATION",
        "llc_classification": None,
        "street": "100 MARKET STREET",
        "city": "SAN FRANCISCO",
        "state": "CA",
        "zip": "94105",
        "tin": "12-3456789",
        "tin_type": "EIN",
        "signature_name": "J. SMITH",
        "signature_date": "04/18/2026",
        "signed": True,
        "expected_decision": "UPDATE_EXISTING",
        "expected_reason": "EXACT_TIN_AND_NAME",
        "expected_supplier_id": "SUP-1001",
        "notes": "Legal suffix variation of the same entity. Name folding should treat as match.",
    },
    {
        "filename": "w9_tin_conflict.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "NORTHWIND TRADING LLC",
        "dba_name": "NORTHWIND",
        "tax_classification": "LLC",
        "llc_classification": "C",
        "street": "9 HARBOR WAY",
        "city": "BOSTON",
        "state": "MA",
        "zip": "02110",
        "tin": "12-3456789",
        "tin_type": "EIN",
        "signature_name": "A. GHOST",
        "signature_date": "05/01/2026",
        "signed": True,
        "expected_decision": "HUMAN_REVIEW",
        "expected_reason": "TIN_NAME_CONFLICT",
        "expected_supplier_id": "SUP-1001",
        "notes": "Existing ACME TIN under a different legal name. Fraud / rename review.",
    },
    {
        "filename": "w9_globex_duplicate.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "GLOBEX CORPORATION",
        "dba_name": "GLOBEX",
        "tax_classification": "C_CORPORATION",
        "llc_classification": None,
        "street": "500 PARK AVENUE",
        "city": "NEW YORK",
        "state": "NY",
        "zip": "10022",
        "tin": "22-1100998",
        "tin_type": "EIN",
        "signature_name": "H. SIMPSON",
        "signature_date": "02/20/2026",
        "signed": True,
        "expected_decision": "HUMAN_REVIEW",
        "expected_reason": "POSSIBLE_DUPLICATE",
        "expected_supplier_id": "SUP-1002",
        "notes": "Near-duplicate name and same address, different TIN.",
    },
    {
        "filename": "w9_new_vendor.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "HOSU LOGISTICS INC",
        "dba_name": "",
        "tax_classification": "C_CORPORATION",
        "llc_classification": None,
        "street": "740 MISSION ROAD",
        "city": "DENVER",
        "state": "CO",
        "zip": "80202",
        "tin": "84-2211099",
        "tin_type": "EIN",
        "signature_name": "M. CHO",
        "signature_date": "06/11/2026",
        "signed": True,
        "expected_decision": "CREATE_NEW",
        "expected_reason": "NO_MATCH",
        "expected_supplier_id": None,
        "notes": "Genuinely new supplier.",
    },
    {
        "filename": "w9_jane_resubmit.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "JANE A SMITH",
        "dba_name": "SMITH CONSULTING",
        "tax_classification": "INDIVIDUAL_SOLE_PROPRIETOR",
        "llc_classification": None,
        "street": "88 PINE STREET",
        "city": "SEATTLE",
        "state": "WA",
        "zip": "98101",
        "tin": "456-78-9012",
        "tin_type": "SSN",
        "signature_name": "JANE A SMITH",
        "signature_date": "07/04/2026",
        "signed": True,
        "expected_decision": "UPDATE_EXISTING",
        "expected_reason": "EXACT_TIN_AND_NAME",
        "expected_supplier_id": "SUP-1003",
        "notes": "Sole proprietor resubmitting an unchanged W-9.",
    },
    {
        "filename": "w9_missing_signature.pdf",
        "revision": "2024-March",
        "form": "W-9",
        "legal_name": "ORBITAL PARTS CO",
        "dba_name": "",
        "tax_classification": "S_CORPORATION",
        "llc_classification": None,
        "street": "16 LAUNCH PAD",
        "city": "HUNTSVILLE",
        "state": "AL",
        "zip": "35801",
        "tin": "63-9988771",
        "tin_type": "EIN",
        "signature_name": None,
        "signature_date": None,
        "signed": False,
        "expected_decision": "HUMAN_REVIEW",
        "expected_reason": "NEW_BUT_UNSIGNED",
        "expected_supplier_id": None,
        "notes": "New supplier, unsigned form. Invalid for tax reporting.",
    },
    {
        "filename": "w9_legacy_2018.pdf",
        "revision": "2018-October",
        "form": "W-9",
        "legal_name": "CEDAR BROOK LLC",
        "dba_name": "CEDAR BROOK",
        "tax_classification": "LLC",
        "llc_classification": "S",
        "street": "12 MAPLE LANE",
        "city": "PORTLAND",
        "state": "OR",
        "zip": "97201",
        "tin": "93-1100223",
        "tin_type": "EIN",
        "signature_name": "R. BROOK",
        "signature_date": "10/02/2019",
        "signed": True,
        "expected_decision": "CREATE_NEW",
        "expected_reason": "NO_MATCH",
        "expected_supplier_id": None,
        "notes": "Older revision, still a valid new supplier. Line 3b absent.",
    },
    {
        "filename": "w8_wrong_form.pdf",
        "revision": "2021",
        "form": "W-8",
        "legal_name": "NORDIC TIMBER AB",
        "dba_name": "",
        "tax_classification": None,
        "llc_classification": None,
        "street": "4 KUNGSTRADGARDEN",
        "city": "STOCKHOLM",
        "state": "",
        "zip": "",
        "tin": "",
        "tin_type": "UNKNOWN",
        "signature_name": "E. LIND",
        "signature_date": "08/08/2026",
        "signed": True,
        "expected_decision": "HUMAN_REVIEW",
        "expected_reason": "WRONG_FORM",
        "expected_supplier_id": None,
        "notes": "Foreign supplier sent a W-8. Service must refuse US onboarding.",
    },
]


def generate_fixtures(root: Path | None = None) -> dict[str, Path]:
    data_dir = (root or ROOT) / "data"
    samples_dir = data_dir / "samples"
    golden_path = data_dir / "golden" / "labels.json"
    master_path = data_dir / "supplier_master.csv"
    samples_dir.mkdir(parents=True, exist_ok=True)
    golden_path.parent.mkdir(parents=True, exist_ok=True)

    _write_master(master_path)
    for sample in SAMPLES:
        if sample["form"] == "W-8":
            _write_w8(samples_dir / sample["filename"], sample)
        else:
            _write_w9(samples_dir / sample["filename"], sample)
    golden_path.write_text(json.dumps(SAMPLES, indent=2), encoding="utf-8")
    return {
        "master": master_path,
        "samples": samples_dir,
        "golden": golden_path,
    }


def _write_master(path: Path) -> None:
    fieldnames = list(SUPPLIERS[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(SUPPLIERS)


def _write_w9(path: Path, sample: dict) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - inch
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(inch, y, f"Form W-9  (Rev. {sample['revision']})")
    y -= 18
    canvas.setFont("Helvetica", 10)
    canvas.drawString(inch, y, "Request for Taxpayer Identification Number and Certification")
    y -= 28
    _line(canvas, "Line 1 Name (as shown on your income tax return)", sample["legal_name"], y)
    y -= 22
    _line(canvas, "Line 2 Business name/disregarded entity name", sample.get("dba_name") or "", y)
    y -= 22
    class_label = (sample.get("tax_classification") or "UNKNOWN").replace("_", " ").title()
    checked = f"[X] {class_label}"
    if sample.get("llc_classification"):
        checked += f"  LLC classification: {sample['llc_classification']}"
    _line(canvas, "Line 3 Federal tax classification", checked, y)
    y -= 22
    _line(canvas, "Line 4 Exempt payee code", "", y)
    y -= 18
    _line(canvas, "FATCA exemption code", "", y)
    y -= 22
    _line(canvas, "Line 5 Address (number, street, and apt. or suite no.)", sample["street"], y)
    y -= 22
    city_line = ", ".join(p for p in [sample["city"], sample["state"]] if p)
    if sample.get("zip"):
        city_line = f"{city_line} {sample['zip']}".strip()
    _line(canvas, "Line 6 City, state, and ZIP code", city_line, y)
    y -= 22
    _line(canvas, "Line 7 List account number(s) (optional)", "", y)
    y -= 36
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(inch, y, "Part I  Taxpayer Identification Number (TIN)")
    y -= 22
    canvas.setFont("Helvetica", 10)
    tin_label = (
        "Social security number"
        if sample.get("tin_type") == "SSN"
        else "Employer identification number"
    )
    _line(canvas, tin_label, sample.get("tin") or "", y)
    y -= 36
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(inch, y, "Part II  Certification")
    y -= 22
    canvas.setFont("Helvetica", 10)
    if sample.get("signed"):
        _line(canvas, "Signature of U.S. person", sample.get("signature_name") or "signed", y)
        y -= 22
        _line(canvas, "Date", sample.get("signature_date") or "", y)
    else:
        _line(canvas, "Signature of U.S. person", "MISSING", y)
        y -= 22
        _line(canvas, "Date", "", y)
    canvas.save()


def _write_w8(path: Path, sample: dict) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - inch
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(inch, y, "Form W-8BEN  (Rev. October 2021)")
    y -= 20
    canvas.setFont("Helvetica", 10)
    canvas.drawString(inch, y, "Certificate of Foreign Status of Beneficial Owner for United States Tax Withholding")
    y -= 28
    _line(canvas, "Name of individual or entity", sample["legal_name"], y)
    y -= 22
    _line(canvas, "Country of citizenship", "Sweden", y)
    y -= 22
    _line(canvas, "Permanent residence address", f"{sample['street']}, {sample['city']}", y)
    y -= 22
    _line(canvas, "Signature", sample.get("signature_name") or "", y)
    canvas.save()


def _line(canvas: Canvas, label: str, value: str, y: float) -> None:
    canvas.setFont("Helvetica", 10)
    canvas.drawString(inch, y, f"{label}: {value}")
