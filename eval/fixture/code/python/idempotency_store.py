"""Idempotency-key bookkeeping for the shipment booking API.

Clients retry booking requests aggressively whenever a mobile network
drops mid-request, and a duplicate booking creates a phantom parcel
that a driver gets dispatched to collect and never finds. Every
booking request carries a client-supplied key, and we refuse to run
the handler twice for the same key within its validity window.
"""

import hashlib
import time
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 86400
IDEMPOTENCY_KEY_MAX_LENGTH = 128


class IdempotencyKeyError(ValueError):
    """Raised for malformed or reused-with-different-payload keys."""


class RequestInFlightError(Exception):
    """Raised when a duplicate request arrives mid-flight."""


@dataclass
class StoredResult:
    payload_hash: str
    response_body: dict
    created_at: float
    status: str = "completed"


def hash_payload(payload: dict) -> str:
    """Fingerprint a request body to detect key reuse with different data."""
    serialized = repr(sorted(payload.items()))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_key_format(key: str) -> None:
    if not key or len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise IdempotencyKeyError(f"idempotency key length invalid: {len(key)}")
    if not all(c.isalnum() or c in "-_" for c in key):
        raise IdempotencyKeyError("idempotency key contains disallowed characters")


class IdempotencyStore:
    """In-memory ledger of recently seen idempotency keys and results.

    A production deployment would back this with a shared cache so any
    API node answers a retry consistently, but the state machine --
    in_flight, completed, expired -- is what actually matters here.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=time.time):
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, StoredResult] = {}

    def _is_expired(self, entry: StoredResult) -> bool:
        return self._clock() - entry.created_at > self.ttl_seconds

    def begin(self, key: str, payload: dict) -> None:
        """Register that we're about to process a request under this key.

        Raises RequestInFlightError so callers can return a 409
        instead of double-booking a shipment.
        """
        validate_key_format(key)
        payload_hash = hash_payload(payload)
        existing = self._entries.get(key)
        if existing and not self._is_expired(existing):
            if existing.status == "in_flight":
                raise RequestInFlightError(f"request for key {key} is already in flight")
            if existing.payload_hash != payload_hash:
                raise IdempotencyKeyError("idempotency key reused with a different payload")
            return  # already completed; caller fetches via get_result
        self._entries[key] = StoredResult(
            payload_hash=payload_hash, response_body={}, created_at=self._clock(), status="in_flight"
        )

    def complete(self, key: str, response_body: dict) -> None:
        entry = self._entries.get(key)
        if entry is None:
            raise IdempotencyKeyError(f"cannot complete unknown key {key}")
        entry.response_body = response_body
        entry.status = "completed"

    def get_result(self, key: str) -> dict | None:
        entry = self._entries.get(key)
        if entry is None or self._is_expired(entry) or entry.status != "completed":
            return None
        return entry.response_body

    def purge_expired(self) -> int:
        """Sweep stale entries so long-running processes don't leak memory."""
        expired_keys = [k for k, v in self._entries.items() if self._is_expired(v)]
        for k in expired_keys:
            del self._entries[k]
        return len(expired_keys)


def build_composite_key(customer_id: str, client_key: str) -> str:
    """Namespace a client key by customer to avoid tenant collisions."""
    return f"{customer_id}:{client_key}"
