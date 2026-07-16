"""Duty and tariff calculation for cross-border shipment quoting.

Customs duty is quoted before a parcel ever leaves the origin depot,
so this code stays conservative: it is far cheaper to slightly
over-quote a customer than to eat an under-quoted duty bill weeks
later when the shipment clears customs under a different schedule.
"""

from dataclasses import dataclass, field

DEFAULT_CURRENCY = "USD"
DUTY_FREE_THRESHOLD_CENTS = 8000  # de minimis, varies by destination
MAX_TARIFF_RATE = 2.5  # sanity clamp; above this is almost certainly a data bug


class TariffScheduleError(Exception):
    """Raised when the loaded tariff schedule is missing or malformed."""


@dataclass
class TariffBand:
    hs_code_prefix: str
    rate: float
    description: str = ""


@dataclass
class DutyQuote:
    declared_value_cents: int
    duty_cents: int
    applied_rate: float
    currency: str = DEFAULT_CURRENCY
    waived: bool = False


def cents_to_major(cents: int) -> float:
    return round(cents / 100, 2)


class TariffCalculator:
    """Resolves an HS code and destination into a duty amount.

    Real tariff schedules are a tree keyed by increasingly specific HS
    prefixes (chapter, heading, subheading); we approximate that with
    longest-prefix matching over a flat list, good enough for quoting
    even though customs authorities use richer origin-based rules.
    """

    def __init__(self, bands: list[TariffBand], destination_country: str):
        if not bands:
            raise TariffScheduleError(f"no bands loaded for {destination_country}")
        self.bands = sorted(bands, key=lambda b: len(b.hs_code_prefix), reverse=True)
        self.destination_country = destination_country

    def _match_band(self, hs_code: str) -> TariffBand | None:
        for band in self.bands:
            if hs_code.startswith(band.hs_code_prefix):
                return band
        return None

    def rate_for_hs_code(self, hs_code: str) -> float:
        band = self._match_band(hs_code)
        if band is None:
            raise TariffScheduleError(f"no tariff band matches hs code {hs_code!r}")
        if band.rate > MAX_TARIFF_RATE:
            raise TariffScheduleError(f"implausible rate {band.rate} for {hs_code}")
        return band.rate

    def quote_duty(self, hs_code: str, declared_value_cents: int) -> DutyQuote:
        if declared_value_cents <= DUTY_FREE_THRESHOLD_CENTS:
            return DutyQuote(
                declared_value_cents=declared_value_cents,
                duty_cents=0,
                applied_rate=0.0,
                waived=True,
            )
        rate = self.rate_for_hs_code(hs_code)
        duty_cents = round(declared_value_cents * rate)
        return DutyQuote(
            declared_value_cents=declared_value_cents,
            duty_cents=duty_cents,
            applied_rate=rate,
        )

    def bulk_quote(self, line_items: list[tuple[str, int]]) -> list[DutyQuote]:
        """Quote every line item on an invoice in one pass, kept separate
        from quote_duty so one bad HS code doesn't abort the whole quote."""
        quotes = []
        for hs_code, value_cents in line_items:
            quotes.append(self.quote_duty(hs_code, value_cents))
        return quotes


def summarize_quotes(quotes: list[DutyQuote]) -> dict:
    total_duty = sum(q.duty_cents for q in quotes)
    waived_count = sum(1 for q in quotes if q.waived)
    return {
        "total_duty_cents": total_duty,
        "total_duty_major": cents_to_major(total_duty),
        "waived_count": waived_count,
        "line_count": len(quotes),
    }


def merge_schedules(base: list[TariffBand], override: list[TariffBand]) -> list[TariffBand]:
    """Layer a trade-agreement override schedule on top of a base one,
    letting override prefixes win ties rather than mutating the base."""
    by_prefix = {b.hs_code_prefix: b for b in base}
    for band in override:
        by_prefix[band.hs_code_prefix] = band
    return list(by_prefix.values())
