"""Quote orchestration: the one place the booking API asks 'what will this cost?'

This module owns no pricing logic of its own. It is glue. It calls the tariff
engine for duty, the linehaul router for transit, and the idempotency store to
make sure a client hammering the retry button does not get three different
quotes for the same parcel and pick whichever it likes.

If you are here because a quote came out wrong, the bug is almost certainly not
in this file. Read the module that raised whatever you saw in the logs.
"""

import logging

from idempotency_store import IdempotencyKeyError, IdempotencyStore, RequestInFlightError
from route_optimizer import LinehaulNetwork, UnreachableDestinationError
from tariff_engine import TariffCalculator, TariffScheduleError

log = logging.getLogger(__name__)

QUOTE_TTL_SECONDS = 900  # a quote is honoured for fifteen minutes, then re-priced


class QuoteUnavailable(Exception):
    """Umbrella failure returned to the API layer as a 503.

    Deliberately opaque: the caller is an HTTP handler and has no business
    branching on which downstream component fell over. The specific cause is
    logged here, once, with the original exception attached.
    """


class QuoteService:
    def __init__(
        self,
        calculator: TariffCalculator,
        network: LinehaulNetwork,
        idempotency: IdempotencyStore,
    ):
        self.calculator = calculator
        self.network = network
        self.idempotency = idempotency

    def quote(self, key: str, request: dict) -> dict:
        try:
            self.idempotency.begin(key, request)
        except RequestInFlightError:
            # A duplicate arrived while the first is still running. The correct
            # answer is 409, not a second quote.
            raise
        except IdempotencyKeyError:
            log.warning("rejected quote request under bad idempotency key")
            raise

        cached = self.idempotency.get_result(key)
        if cached:
            return cached

        try:
            plan = self.network.find_best_route(
                request["origin_hub"], request["destination_hub"]
            )
        except UnreachableDestinationError as exc:
            # Not a bug and not a 500: some hub pairs genuinely have no route.
            # Dispatch handles these by hand. See the linehaul runbook.
            log.info("no route available for quote: %s", exc)
            raise QuoteUnavailable("no linehaul route") from exc

        try:
            duty = self.calculator.quote_duty(
                request["hs_code"], request["declared_value_cents"]
            )
        except TariffScheduleError as exc:
            log.error("tariff schedule problem while quoting: %s", exc)
            raise QuoteUnavailable("duty could not be quoted") from exc

        body = {
            "transit_hours": plan.total_transit_hours,
            "linehaul_cost_cents": plan.total_cost_cents,
            "duty_cents": duty.duty_cents,
            "duty_waived": duty.waived,
            "total_cents": plan.total_cost_cents + duty.duty_cents,
        }
        self.idempotency.complete(key, body)
        return body

    def quote_many(self, key_prefix: str, requests: list[dict]) -> list[dict]:
        """Quote a whole basket. One bad line does not sink the others."""
        results = []
        for index, request in enumerate(requests):
            try:
                results.append(self.quote(f"{key_prefix}:{index}", request))
            except QuoteUnavailable as exc:
                results.append({"error": str(exc), "line": index})
        return results
