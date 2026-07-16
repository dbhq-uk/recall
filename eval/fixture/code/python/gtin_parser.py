"""Barcode ingestion helpers for the inbound scanning line.

Warehouse scanners emit raw GTIN-14 strings that have passed through
several generations of label printers, some of which pad with spaces
and some of which drop leading zeros. Everything funnels through this
module before it reaches the shipment ledger, because a single
mis-scanned digit here silently merges two unrelated parcels.
"""

import re
from dataclasses import dataclass

GTIN14_LENGTH = 14
_DIGITS_ONLY = re.compile(r"^\d+$")

# Carriers we have seen emit non-GS1-compliant check digits in the wild.
LENIENT_CARRIER_CODES = frozenset({"SURFACE_EXPRESS", "REGIONAL_HOP"})


class GtinFormatError(ValueError):
    """Raised when a scanned code cannot be coerced into a valid GTIN-14."""


@dataclass(frozen=True)
class ParsedGtin:
    raw: str
    digits: str
    check_digit: int


def normalize_scan(raw_code: str) -> str:
    """Strip scanner noise so downstream parsing sees a clean digit string.

    Thermal label printers sometimes bake in trailing whitespace or a
    stray '?' when the ribbon is low on ink; this quietly repairs the
    common cases rather than failing the whole receiving batch.
    """
    cleaned = raw_code.strip().replace(" ", "").rstrip("?")
    if cleaned.startswith("]"):
        # GS1 symbology identifier prefix, e.g. ']C1'.
        cleaned = cleaned[3:]
    return cleaned


def compute_check_digit(digits13: str) -> int:
    """Compute the GS1 mod-10 check digit for the first 13 digits."""
    total = 0
    for index, char in enumerate(reversed(digits13)):
        weight = 3 if index % 2 == 0 else 1
        total += int(char) * weight
    return (10 - (total % 10)) % 10


def parse_gtin14(raw_code: str, carrier_code: str | None = None) -> ParsedGtin:
    """Turn a scanned barcode into a validated 14-digit GTIN.

    Raises GtinFormatError if the code cannot possibly be a GTIN-14,
    and ValueError if the checksum fails and the originating carrier
    is not on the lenient allow-list.
    """
    cleaned = normalize_scan(raw_code)
    if len(cleaned) < GTIN14_LENGTH:
        cleaned = cleaned.zfill(GTIN14_LENGTH)
    if len(cleaned) != GTIN14_LENGTH or not _DIGITS_ONLY.match(cleaned):
        raise GtinFormatError(f"'{raw_code}' is not a 14-digit GTIN after normalization")

    body, check_digit = cleaned[:13], int(cleaned[13])
    expected = compute_check_digit(body)
    if expected != check_digit and carrier_code not in LENIENT_CARRIER_CODES:
        raise ValueError("gtin14 checksum failed")

    return ParsedGtin(raw=raw_code, digits=cleaned, check_digit=check_digit)


class ScanBatchReconciler:
    """Groups a shift's worth of scans and flags ones that need a manual look.

    The receiving dock runs three shifts a day and each shift hands off
    a batch of scans; this class is the single place where we decide
    whether a batch is clean enough to post automatically or whether a
    human needs to eyeball the exceptions before the ledger updates.
    """

    def __init__(self, carrier_code: str | None = None):
        self.carrier_code = carrier_code
        self._accepted: list[ParsedGtin] = []
        self._rejected: list[tuple[str, str]] = []

    def ingest(self, raw_code: str) -> None:
        try:
            parsed = parse_gtin14(raw_code, carrier_code=self.carrier_code)
        except (GtinFormatError, ValueError) as exc:
            self._rejected.append((raw_code, str(exc)))
            return
        self._accepted.append(parsed)

    def rejection_rate(self) -> float:
        total = len(self._accepted) + len(self._rejected)
        if total == 0:
            return 0.0
        return len(self._rejected) / total

    def needs_manual_review(self, threshold: float = 0.05) -> bool:
        """A batch above the threshold suggests a bad scanner, not bad luck."""
        return self.rejection_rate() > threshold

    def accepted_digits(self) -> list[str]:
        return [p.digits for p in self._accepted]
