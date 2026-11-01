"""TIN handling, redaction, and tenant-scoped hashing.

The prototype keeps matching in-process, so it still sees raw digits.
What this module guarantees: raw TINs never appear in logs, evaluation
summaries, or the default CLI payload.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from w9_onboarding.models import TinType

_NON_DIGIT = re.compile(r"\D+")
_LOG_TIN_PATTERN = re.compile(
    r"\b(\d{3}-\d{2}-\d{4}|\d{2}-\d{7}|\d{9})\b"
)


def normalize_tin(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return _NON_DIGIT.sub("", raw)


def detect_tin_type(digits: str, hint: Optional[str] = None) -> TinType:
    if hint:
        upper = hint.upper()
        if "SSN" in upper or "SOCIAL" in upper:
            return TinType.SSN
        if "EIN" in upper or "EMPLOYER" in upper:
            return TinType.EIN
    if len(digits) != 9:
        return TinType.UNKNOWN
    return TinType.UNKNOWN


def format_tin(digits: str, tin_type: TinType) -> Optional[str]:
    if len(digits) != 9:
        return digits or None
    if tin_type == TinType.SSN:
        return f"{digits[0:3]}-{digits[3:5]}-{digits[5:9]}"
    return f"{digits[0:2]}-{digits[2:9]}"


def redact_tin(digits: str, tin_type: TinType) -> Optional[str]:
    if not digits:
        return None
    last4 = digits[-4:] if len(digits) >= 4 else digits
    if tin_type == TinType.SSN:
        return f"***-**-{last4}"
    if tin_type == TinType.EIN:
        return f"**-***{last4}"
    return f"*****{last4}"


def tin_last4(digits: str) -> Optional[str]:
    if len(digits) < 4:
        return None
    return digits[-4:]


def hash_tin(digits: str, tenant_id: str, salt: str = "w9-onboarding-v1") -> str:
    """Tenant-scoped hash so the same TIN is not a cross-tenant join key."""
    material = f"{salt}|{tenant_id}|{digits}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def looks_like_ssn_format(digits: str) -> bool:
    if len(digits) != 9:
        return False
    area, group, serial = digits[0:3], digits[3:5], digits[5:9]
    if area == "000" or area == "666" or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def looks_like_ein_format(digits: str) -> bool:
    # IRS campus prefixes are not worth encoding here; format is the gate.
    return len(digits) == 9


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _LOG_TIN_PATTERN.sub("[REDACTED_TIN]", str(record.msg))
        if record.args:
            redacted = []
            for arg in record.args:
                if isinstance(arg, str):
                    redacted.append(_LOG_TIN_PATTERN.sub("[REDACTED_TIN]", arg))
                else:
                    redacted.append(arg)
            record.args = tuple(redacted)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
