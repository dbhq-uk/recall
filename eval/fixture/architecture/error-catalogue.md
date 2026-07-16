# On-call error catalogue

## How to use this page

This is a triage aid, not a reference. For every error name we have seen page
somebody, it tells you three things: how bad it is, what the customer experiences,
and which runbook to open. It deliberately does **not** tell you what the error
means or under what conditions the code raises it. That information lives in the
module that raises it, and it goes stale within a release if you copy it here —
we tried, it went stale, we stopped.

So: use this page to decide whether to get out of bed. Read the source to decide
what to do.

Sorted by severity, then alphabetically.

## SEV-2: customer-visible, page immediately

| Error | What the customer sees | Runbook |
| --- | --- | --- |
| `SlotCapacityExceededError` | Checkout offers no delivery slots, or the chosen slot silently changes | `runbook/slots` |
| `RateCardNotFoundError` | Quote request returns a 500; the customer sees "pricing unavailable" | `runbook/pricing` |
| `ErrLedgerMismatch` | Nothing yet — but the end-of-day manifest will not transmit, and by morning there are parcels on a truck with no paperwork | `runbook/manifest` |
| `IdempotencyKeyError` | A booking retry returns 400 instead of the original booking | `runbook/booking` |

## SEV-3: degraded, handle in hours

| Error | What the customer sees | Runbook |
| --- | --- | --- |
| `RetryBudgetExhaustedError` | A carrier webhook never lands; tracking page stops updating for that consignment | `runbook/webhooks` |
| `UnreachableDestinationError` | Dispatch cannot plan a route; the consignment sits unassigned in the queue | `runbook/linehaul` |
| `ErrStaleEvent` | Usually nothing. It is normally the system working correctly. Investigate only if the *rate* jumps | `runbook/tracking` |
| `RequestInFlightError` | A duplicate booking request gets a 409, which is the correct answer | none needed |
| `ErrTerminalStatus` | A late scan is refused on an already-delivered shipment | `runbook/tracking` |

## SEV-4: internal only, no page

| Error | Impact | Runbook |
| --- | --- | --- |
| `ERR_MIGRATION_NO_DOWN` | A pull request fails CI. Nothing reaches production | `runbook/ci` |
| `ERR_CONSIGNMENT_LOCKED` | Two dispatchers editing the same consignment; second one retries | none needed |
| `TariffScheduleError` | Duty quoting falls back to manual for the affected destination | `runbook/customs` |
| `GtinFormatError` | A scan is rejected at the receiving dock and queued for manual review | `runbook/receiving` |
| `ErrNoKeywordMatch` | A commercial-invoice line is routed to a human classifier | none needed |
| `ErrLowConfidence` | As above. The classifier is being conservative on purpose | none needed |

## Names that look alike and are not

Every one of these has cost somebody at least twenty minutes. Read the whole name
before you act on it:

- `RetryBudgetExhaustedError` is thrown by the webhook delivery path.
  `MAX_RETRY_BUDGET_MS` is an unrelated deployment-level timeout in the platform
  configuration and has nothing to do with it — the similarity in name is an
  accident we have not yet been bothered enough to fix.
- `ErrLedgerMismatch` (manifest reconciliation, ours against the ledger) is not
  `ErrLedgerLocked` (someone is mid-edit; just retry) and is emphatically not the
  ledger reconciler's `Overcharge`/`Undercharge` variance kinds, which are about
  what a *carrier* invoiced us, not about what we put on a manifest.
- `ErrStaleEvent` (tracking, an out-of-order status update) is not
  `ErrStaleManifest` (a manifest draft older than the current dispatch day).
- `IdempotencyKeyError` is not `RequestInFlightError`. One of them means the
  client did something wrong. The other means the client did something right,
  twice, quickly.

## Adding an entry

Add a row when an error has paged a human at least once. Do not add a row
speculatively for every error type in the codebase; a catalogue that lists
everything is a catalogue nobody reads at 3am.
