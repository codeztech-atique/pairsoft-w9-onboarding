"""W-9 extraction and supplier onboarding service (prototype).

Package layout (simple map):
  pipeline.py     — ingest → extract → validate → match
  matching.py     — create / update / review rules
  models.py       — versioned JSON API contract
  validation.py   — quality / blocking flags
  extraction/     — form parser (+ optional LLM)
  security.py     — TIN redaction
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "1.0"
