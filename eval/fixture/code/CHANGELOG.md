# Changelog — shipment platform libraries

All notable changes to the shared logistics libraries, newest first. One entry per
release, one line per change, and a link to the module rather than an explanation
of it — a changelog that explains behaviour is a changelog that contradicts the
code within two releases.

Format loosely follows Keep a Changelog. Versions are per-library, not global,
which is confusing and which we have decided to live with.

## 2026-06-02

### Changed

- `TariffCalculator` now sorts bands by prefix length at construction rather than
  on every lookup. No behavioural change; roughly 4x faster on the bulk path.
- `ScanBatchReconciler.needs_manual_review()` threshold is now a constructor
  argument rather than a hard-coded default. Receiving asked for it.

### Fixed

- `RateCardNotFoundError` was being swallowed by `cheapestCarrierForZone()` in a
  way that made a zone with *no* servicing carriers look identical to a zone
  where every carrier was over the weight limit. It now still returns `null`, but
  logs which of the two happened.

## 2026-04-17

### Added

- Gateway support for the firmware 4.x scan guns, which use a different start
  sentinel from `FRAME_START_BYTE`. Both are now accepted. See the gateway module
  for the sniffing logic.
- `MAX_ACCEPTABLE_COUNT_VARIANCE` in the scanner gateway, for parcel counts at the
  dock. Named to be hard to confuse with the reconciler's
  `MAX_ACCEPTABLE_VARIANCE_CENTS`, which it is unrelated to. It has been confused
  with it anyway.

### Deprecated

- `LegacyTariffCalculator` is gone for good this time. It was already gone. Two
  services were still importing it from a vendored copy.

## 2026-02-09

### Fixed

- `RetryBudgetExhaustedError` was reported with an off-by-one attempt count in the
  message — it said `n` where it meant `n + 1`. Purely cosmetic, but it made every
  webhook postmortem's arithmetic wrong by one for about eight months.
- Quarantine threshold is no longer re-read from the environment on every call.

### Changed

- `MAX_RETRY_BUDGET_MS` moved from a code constant into SSM Parameter Store. This
  is the platform request timeout and is not related to the webhook retry budget,
  regardless of what the name suggests.

## 2025-11-24

### Added

- `ErrStaleManifest` and `ErrLedgerLocked` in the dispatch coordinator. Neither is
  `ErrLedgerMismatch`; the on-call error catalogue explains which is which and
  what to do about each.

### Fixed

- `ErrStaleEvent` was being returned for events with *equal* timestamps, not just
  earlier ones. A depot scan and a carrier webhook landing in the same
  millisecond is rare but not impossible, and the second one was being dropped.

## 2025-09-30

### Added

- `SlotCapacityExceededError` is now thrown with the depot id in the message
  rather than just the slot. Ops could not tell which depot was full.
- `chooseFallbackSlot()`, so the checkout can offer an alternative window instead
  of a dead end.

## 2025-07-15

### Added

- `IdempotencyStore` and `IdempotencyKeyError`, replacing the ad-hoc `seen_keys`
  set that three services each had their own slightly different copy of.
- `RequestInFlightError`, distinct from `IdempotencyKeyError`, because a client
  retrying correctly and a client sending rubbish are different situations and
  deserve different status codes.

## 2025-05-06

### Added

- `UnreachableDestinationError` in the linehaul router. Previously a hub pair with
  no path returned an empty `RoutePlan`, which every caller then treated as a
  free, instantaneous route. This was as bad as it sounds.

### Changed

- `MAX_HOPS` lowered from 8 to 6 after dispatch confirmed they would never book a
  seven-leg route regardless of what the maths said.

## 2025-02-11

### Added

- Initial extraction of `manifest`, `tracking`, `customs` and the scanner protocol
  from core-api into shared libraries. `ErrLedgerMismatch`, `ErrStaleEvent` and
  `FRAME_START_BYTE` all date from here and were unchanged in the move.
