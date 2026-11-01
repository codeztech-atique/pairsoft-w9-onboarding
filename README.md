# PairSoft W-9 Supplier Onboarding

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

AI-powered service that ingests an IRS Form W-9, extracts the supplier tax identity with per-field confidence, validates it, and returns a structured **create / update / human review** decision against a tenant supplier master.

This is the working prototype for the PairSoft Central AI Services case study. The design behind the code is in [DESIGN.md](DESIGN.md). This README is what to run, what the API returns, and what to look at first.

**Repository:** [codeztech-atique/pairsoft-w9-onboarding](https://github.com/codeztech-atique/pairsoft-w9-onboarding)

---

## What this service does

Accounts Payable cannot pay a supplier until it knows who that supplier is. In the United States that starts with a W-9. The form arrives as a clean PDF, a phone photo, an older 2018 layout, or sometimes the wrong form entirely (a W-8).

This service is the front door:

1. **Ingest** a W-9 PDF or image.
2. **Extract** Line 1–7, TIN, tax classification, address, and signature, each with a confidence score.
3. **Validate** format, required fields, signature, and classification vs TIN type.
4. **Match** the extracted identity to the customer’s existing supplier master.
5. **Decide** one of three outcomes for a downstream PairSoft product:
   - `CREATE_NEW` — no reasonable existing supplier
   - `UPDATE_EXISTING` — same TIN and legal name, no material change
   - `HUMAN_REVIEW` — conflict, material change, duplicate risk, unsigned form, or wrong form

It does **not** write the supplier master. Another PairSoft service consumes the JSON and creates, updates, or opens a review task.

---

## What to look at first

If you have 15 minutes before a walkthrough, go in this order:

1. [DESIGN.md](DESIGN.md) — architecture, match policy, security, cost model.
2. [`src/w9_onboarding/models.py`](src/w9_onboarding/models.py) — the versioned API contract.
3. [`src/w9_onboarding/matching.py`](src/w9_onboarding/matching.py) — create vs update vs review.
4. [`data/samples/`](data/samples/) — the ten labeled documents used in evaluation.
5. Run `w9-onboard process` and `w9-onboard evaluate` below.

---

## Pipeline

```
W-9 PDF / image
        │
        ▼
   Ingestion gate          type sniff, text recovery, quality score
        │
        ▼
   Extraction              form-aware parser (+ optional LLM refine)
        │
        ▼
   Validation              TIN format, signature, address, flags
        │
        ▼
   Matching                tenant master: TIN, folded name, address
        │
        ▼
   OnboardingResponse      JSON: fields, confidence, flags, decision
```

**Opinionated rules**

- Models extract. Rules decide. An LLM never picks create vs update.
- A TIN match is never enough by itself. The legal name must agree.
- Material changes (address, tax classification, DBA) go to review, not a silent update.
- Same name and address with a *different* TIN is a possible duplicate, not an auto-create.
- A W-8 is a wrong-form event. The service will not onboard a US supplier from it.
- Raw TINs never appear in logs or the default CLI payload.

---

## API contract

The CLI prints the same object a REST handler would return. Schema version is `1.0`.

```json
{
  "request_id": "uuid",
  "schema_version": "1.0",
  "document": {
    "filename": "w9_acme_resubmit.pdf",
    "detected_form": "W-9",
    "form_revision": "2024-March",
    "quality_score": 0.91
  },
  "extraction": {
    "legal_name": { "value": "ACME CORPORATION", "confidence": 0.9, "source": "heuristic" },
    "tin": {
      "value": null,
      "value_redacted": "**-***6789",
      "last4": "6789",
      "tin_type": "EIN",
      "confidence": 0.95
    }
  },
  "overall_confidence": 0.88,
  "validation": {
    "passed": true,
    "blocking": false,
    "flags": [{ "code": "TIN_FORMAT_VALID", "severity": "info", "message": "..." }]
  },
  "match": {
    "decision": "UPDATE_EXISTING",
    "reason_code": "EXACT_TIN_AND_NAME",
    "reasoning": "TIN and legal name match SUP-1001 with no material changes.",
    "matched_supplier_id": "SUP-1001",
    "material_changes": [],
    "candidates": []
  },
  "audit": {
    "pipeline_version": "0.1.0",
    "extractor_path": "heuristic",
    "tenant_id": "demo-tenant"
  }
}
```

Pass `--include-tin` only when a downstream write path needs the raw value. Pydantic models in `models.py` are the source of truth.

---

## Setup

Python 3.11+ (developed on 3.12). No Docker, no cloud account, and no API key required. On macOS the default `python3` may still be 3.9 — use `python3.12` if so.

```bash
git clone https://github.com/codeztech-atique/pairsoft-w9-onboarding.git
cd pairsoft-w9-onboarding
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional:

- `OPENAI_API_KEY` plus `--use-llm` to run the consensus extraction pass described in the design.
- Tesseract only if you want the image / OCR path. Digital PDFs do not need it.

---

## Run

Generate the sample supplier master and W-9s (safe to re-run):

```bash
w9-onboard generate-samples
```

Process one document. Default output redacts the TIN:

```bash
w9-onboard process data/samples/w9_acme_resubmit.pdf \
  --master data/supplier_master.csv \
  --out outputs/acme_resubmit.json
```

Score the labeled set:

```bash
w9-onboard evaluate --out outputs/evaluation.json
```

Directional unit tests (not an exhaustive suite):

```bash
pytest -q
```

Expected eval on the shipped golden set:

| Metric | Result |
|---|---|
| Cases | 10 |
| Decision accuracy | 100% |
| Reason-code accuracy | 100% |
| Field accuracy | 100% |

---

## Sample cases

All names and TINs are synthetic.

| File | What it tests | Expected decision |
|---|---|---|
| `w9_acme_resubmit.pdf` | Clean resubmit, same identity | `UPDATE_EXISTING` |
| `w9_acme_name_variant.pdf` | `ACME CORP.` vs `ACME CORPORATION` | `UPDATE_EXISTING` |
| `w9_acme_moved.pdf` | Same TIN and name, new address | `HUMAN_REVIEW` / material change |
| `w9_tin_conflict.pdf` | Existing TIN, different legal name | `HUMAN_REVIEW` / TIN-name conflict |
| `w9_globex_duplicate.pdf` | Same name and address, different TIN | `HUMAN_REVIEW` / possible duplicate |
| `w9_new_vendor.pdf` | No reasonable candidate | `CREATE_NEW` |
| `w9_jane_resubmit.pdf` | Sole proprietor SSN resubmit | `UPDATE_EXISTING` |
| `w9_missing_signature.pdf` | New vendor, unsigned W-9 | `HUMAN_REVIEW` |
| `w9_legacy_2018.pdf` | 2018 revision, new LLC | `CREATE_NEW` |
| `w8_wrong_form.pdf` | Foreign W-8 sent instead of W-9 | `HUMAN_REVIEW` / wrong form |

---

## Project layout

```
DESIGN.md                 architecture, cost, security, deferred work
README.md                 how to run it and what the API returns
LICENSE                   MIT
src/w9_onboarding/
  models.py               versioned response contract
  pipeline.py             ingest → extract → validate → match
  extraction/             form parser, optional LLM, consensus merge
  validation.py           machine-readable flags
  matching.py             create / update / review policy
  security.py             TIN normalize, redact, tenant-scoped hash
  evaluation.py           golden-set scoring
  cli.py                  process | evaluate | generate-samples
data/
  supplier_master.csv     demo tenant master
  samples/                labeled W-9 and W-8 PDFs
  golden/labels.json      expected extraction and decisions
tests/                    directional tests
```

---

## Tradeoffs

- **Local heuristic parser instead of Azure Document Intelligence.** The brief asked for a laptop-runnable prototype. The response schema and match policy are the production pieces; the parser stands in for a custom DI model.
- **Rules decide, models extract.** Create vs update has to be explainable to AP and audit.
- **TIN match never auto-updates by itself.** Name must agree. Material changes go to review. See DESIGN.md §5.
- **LLM is opt-in.** Off by default so a hiring panel can run this without a key, and so PII does not leave the box unless someone chooses.
- **CLI, not a web UI or Flask app.** The brief said a command-line entry point is enough and explicitly ruled out a user interface. The JSON is the API.

## What was deferred

Production DI training, IRS TIN Matching, OFAC / sanctions, a real master-data service, auth, containers, and a reviewer UI. Bank-account reuse fraud needs the master, not the W-9. Multi-country intake is a form-family plugin, not in v1.

## If I had eight more hours

1. A degraded-image golden set so the extraction ceiling is visible.
2. An Azure Document Intelligence adapter behind the same `ExtractedFields` type.
3. Sanctions and TIN Matching flags as adapters, not stubs.
4. Idempotent persistence on `sha256(document)`.

---

## License

MIT. See [LICENSE](LICENSE).
