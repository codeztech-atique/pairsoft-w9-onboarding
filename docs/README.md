# PairSoft W-9 Onboarding — Simple Guide

This document explains the project in plain language: the problem, what we built, what each file does, and how to run it.

For the full technical design (architecture, cost, security), see [DESIGN.md](../DESIGN.md).  
For setup commands and API shape, see [README.md](../README.md).

---

## The problem (simple)

A company cannot pay a US supplier until it knows who that supplier is for tax purposes.

That identity comes from an **IRS Form W-9**. The form has:

- Legal company name (or person name)
- Tax ID (EIN for a company, SSN for a person)
- Tax classification (C-Corp, LLC, sole proprietor, etc.)
- Address
- Signature

In real life the form arrives as:

- A clean PDF
- A phone photo
- An older 2018 layout
- Sometimes the **wrong form** (a W-8, which is for foreign suppliers)

Someone in Accounts Payable then has to:

1. Read the form
2. Check if this supplier already exists in the company list
3. Decide: **create new**, **update existing**, or **ask a human**

Doing that by hand is slow. Doing it badly causes:

- Duplicate payments
- Broken spend reports
- Failed 1099 tax forms
- Fraud (for example: same tax ID, different company name, or a sudden address change that redirects money)

---

## What we built (simple)

We built a small AI / rules service that:

1. Reads a W-9 PDF (or image)
2. Extracts the important fields, each with a confidence score
3. Checks if the form looks valid (signature, tax ID format, etc.)
4. Compares it to that customer’s supplier list
5. Returns one clear decision:

| Decision | Meaning |
|---|---|
| `CREATE_NEW` | This looks like a brand-new supplier |
| `UPDATE_EXISTING` | Same supplier as before; safe to refresh the record |
| `HUMAN_REVIEW` | Something is risky or unclear — a person should look |

Important: this service **does not write** the supplier database. It returns JSON. Another PairSoft product would create, update, or open a review task.

### Core opinion

> **Models extract. Rules decide.**

An LLM can help read messy text. It never chooses create vs update by itself. That decision must be explainable to AP and to an auditor.

Also: **a tax ID match alone is never enough to auto-update.** The legal name must agree too. A stolen or reused EIN under a new name is how payment fraud often starts.

---

## How the pipeline works

```
W-9 PDF / image
      │
      ▼
 1. Ingest        Open the file, pull out text, score quality
      │
      ▼
 2. Extract       Read name, tax ID, address, signature (+ confidence)
      │
      ▼
 3. Validate      Is the form usable? Missing signature? Wrong form?
      │
      ▼
 4. Match         Compare to supplier_master.csv for this customer
      │
      ▼
 5. Decide        CREATE_NEW / UPDATE_EXISTING / HUMAN_REVIEW
                  (JSON response with reason codes)
```

---

## Real examples from our sample set

We keep a demo supplier list (`data/supplier_master.csv`) with fake companies like ACME, Globex, and Jane Smith.

| Sample file | What happens | Decision |
|---|---|---|
| `w9_acme_resubmit.pdf` | ACME sends the same W-9 again | `UPDATE_EXISTING` |
| `w9_acme_name_variant.pdf` | Name says `ACME CORP.` instead of `ACME CORPORATION` | `UPDATE_EXISTING` (name folding) |
| `w9_acme_moved.pdf` | Same ACME, new street address | `HUMAN_REVIEW` (material change) |
| `w9_tin_conflict.pdf` | ACME’s tax ID, but name is Northwind | `HUMAN_REVIEW` (possible fraud) |
| `w9_globex_duplicate.pdf` | Same name/address as Globex, different tax ID | `HUMAN_REVIEW` (possible duplicate) |
| `w9_new_vendor.pdf` | Brand new company | `CREATE_NEW` |
| `w9_missing_signature.pdf` | New company, but unsigned | `HUMAN_REVIEW` |
| `w8_wrong_form.pdf` | Foreign W-8 instead of W-9 | `HUMAN_REVIEW` |

On the labeled set of 10 documents, the prototype scores **100%** on decision, reason code, and field accuracy.

---

## What every important file / folder is for

### Top level

| Path | What it is |
|---|---|
| `README.md` | How to install, run, and what the JSON API looks like |
| `DESIGN.md` | Full architecture, match policy, security, cost model |
| `docs/README.md` | This simple guide |
| `pyproject.toml` | Python package config (how the CLI is installed) |
| `requirements.txt` | Dependency list |
| `LICENSE` | MIT license |
| `AI_Case_Study_W9_Supplier_Onboarding_1.pdf` | Original PairSoft case study brief |

### Data

| Path | What it is |
|---|---|
| `data/supplier_master.csv` | Fake customer supplier list used for matching |
| `data/samples/` | Ten sample W-9 / W-8 PDF files |
| `data/golden/labels.json` | Expected answers for each sample (used by evaluate) |
| `outputs/` | JSON results when you run the CLI |

### Source code (`src/w9_onboarding/`)

| File | Plain English job |
|---|---|
| `cli.py` | Command line: `process`, `evaluate`, `generate-samples` |
| `pipeline.py` | Glue that runs ingest → extract → validate → match |
| `models.py` | The JSON contract (fields, decision, audit) |
| `ingestion.py` | Open PDF/image and recover text |
| `extraction/` | Read W-9 lines from text (parser + optional LLM) |
| `extraction/form_parser.py` | Local stand-in for Azure Document Intelligence |
| `extraction/llm_extractor.py` | Optional OpenAI cleanup pass |
| `extraction/consensus.py` | Merge heuristic + LLM; lower confidence if they disagree |
| `validation.py` | Flag problems (missing TIN, unsigned, wrong form, etc.) |
| `matching.py` | Create / update / review decision rules |
| `normalize.py` | Fold names/addresses so `ACME CORP.` ≈ `ACME CORPORATION` |
| `security.py` | Hide tax IDs in logs/output (`**-***6789`) |
| `master.py` | Load the supplier CSV/JSON |
| `evaluation.py` | Score the pipeline against golden labels |
| `samples.py` | Generate the demo PDFs and master file |

### Tests

| Path | What it is |
|---|---|
| `tests/test_matching.py` | Checks create / update / review rules |
| `tests/test_validation.py` | Checks validation flags |
| `tests/test_extraction.py` | Checks field extraction on samples |

---

## How to run it

From the project root:

```bash
# one-time setup
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# process one form
PYTHONPATH=src python -m w9_onboarding process data/samples/w9_acme_resubmit.pdf \
  --master data/supplier_master.csv

# score all 10 labeled samples
PYTHONPATH=src python -m w9_onboarding evaluate
```

Useful samples to try:

```bash
# brand new supplier → CREATE_NEW
PYTHONPATH=src python -m w9_onboarding process data/samples/w9_new_vendor.pdf --master data/supplier_master.csv

# tax ID conflict → HUMAN_REVIEW
PYTHONPATH=src python -m w9_onboarding process data/samples/w9_tin_conflict.pdf --master data/supplier_master.csv

# address change → HUMAN_REVIEW
PYTHONPATH=src python -m w9_onboarding process data/samples/w9_acme_moved.pdf --master data/supplier_master.csv
```

---

## What we did **not** build (on purpose)

- A web UI
- Writing directly to a real supplier database
- Azure Document Intelligence training (prototype uses a local parser with the same response shape)
- Live IRS TIN Matching / OFAC sanctions checks
- Multi-country forms (US W-9 only in v1)

Those belong in production adapters. The prototype focuses on the **contract** and the **match policy**.

---

## One-line interview answer

> AP needs a trustworthy supplier identity from a W-9. We built a pipeline that extracts the form, validates it, matches it to the tenant supplier master, and returns create, update, or human review — and a tax ID match alone never auto-updates, because that is how payment fraud starts.
