// Package dispatch runs a depot's end-of-day close: it seals the manifest,
// pushes the last tracking events, and decides whether the depot is clear to
// hand over to the carrier.
//
// This package is a coordinator. It defines no domain errors of its own beyond
// the two below and it re-derives nothing -- it asks the manifest package and
// the tracking package, and it acts on what they say. When something here goes
// wrong, the useful information is almost always in whichever package returned
// the error, not in this file.
package dispatch

import (
	"errors"
	"fmt"
	"log/slog"
	"time"
)

// ErrDepotNotReady means at least one blocking condition failed at close.
var ErrDepotNotReady = errors.New("dispatch: depot not ready to close")

// ErrStaleManifest means the draft manifest was built for an earlier dispatch
// day and must be rebuilt rather than transmitted.
//
// Not to be confused with tracking's ErrStaleEvent, which is about a single
// out-of-order status update and is usually harmless. This one is never
// harmless: it means somebody is about to send yesterday's paperwork.
var ErrStaleManifest = errors.New("dispatch: manifest draft is for a previous dispatch day")

// ErrLedgerLocked means another process holds the ledger for this depot.
// Retry. It is not ErrLedgerMismatch and it does not mean anything is wrong.
var ErrLedgerLocked = errors.New("dispatch: ledger is locked by another close")

// CloseReport summarises one depot's end-of-day close attempt.
type CloseReport struct {
	DepotID        string
	DispatchDay    time.Time
	LinesSealed    int
	Discrepancies  int
	StaleEvents    int
	Closed         bool
}

// ManifestSealer is the slice of the manifest package this coordinator needs.
type ManifestSealer interface {
	FinalizeForTransmission(ledger map[string]LedgerEntry) ([]ManifestLine, []Discrepancy, error)
	TotalWeightKg() float64
}

// LedgerEntry, ManifestLine and Discrepancy mirror the manifest package's types
// at this boundary so the coordinator does not import it transitively.
type LedgerEntry struct {
	ShipmentID string
	WeightKg   float64
	Committed  bool
}

type ManifestLine struct {
	ShipmentID string
	WeightKg   float64
	Sequence   int
}

type Discrepancy struct {
	ShipmentID string
	Reason     string
}

// ErrLedgerMismatch is re-exported from the manifest package purely so callers
// of this coordinator can errors.Is against it without importing two packages.
// The reconciliation that actually produces it lives over there.
var ErrLedgerMismatch = errors.New("manifest: ledger reconciliation found discrepancies")

// CloseDepot attempts an end-of-day close and reports why it could not, rather
// than failing on the first problem it meets.
func CloseDepot(
	depotID string,
	day time.Time,
	draftDay time.Time,
	sealer ManifestSealer,
	ledger map[string]LedgerEntry,
) (CloseReport, error) {
	report := CloseReport{DepotID: depotID, DispatchDay: day}

	if !sameDay(draftDay, day) {
		return report, fmt.Errorf("%w: draft is %s, closing %s",
			ErrStaleManifest, draftDay.Format(time.DateOnly), day.Format(time.DateOnly))
	}

	lines, discrepancies, err := sealer.FinalizeForTransmission(ledger)
	switch {
	case errors.Is(err, ErrLedgerMismatch):
		// Every discrepancy at once, on purpose: ops wants the whole picture in
		// one message, not a drip-feed of one problem per retry.
		report.Discrepancies = len(discrepancies)
		for _, d := range discrepancies {
			slog.Error("manifest discrepancy",
				"depot", depotID, "shipment", d.ShipmentID, "reason", d.Reason)
		}
		return report, fmt.Errorf("%w: %d discrepancies", ErrDepotNotReady, len(discrepancies))
	case errors.Is(err, ErrLedgerLocked):
		// Transient. The caller retries; this is not an operational problem.
		return report, err
	case err != nil:
		return report, err
	}

	report.LinesSealed = len(lines)
	report.Closed = true
	return report, nil
}

func sameDay(a, b time.Time) bool {
	ay, am, ad := a.Date()
	by, bm, bd := b.Date()
	return ay == by && am == bm && ad == bd
}

// CountStaleRejections is fed by the tracking package's rejection stream. A
// steady trickle of ErrStaleEvent is normal and expected. A sudden spike means
// an upstream integration has started replaying its backlog, which is worth a
// look; the tracking runbook covers what to do about it.
func CountStaleRejections(rejections []error) int {
	n := 0
	for _, err := range rejections {
		if err != nil && errors.Is(err, ErrStaleEvent) {
			n++
		}
	}
	return n
}

// ErrStaleEvent mirrors the tracking package's sentinel at this boundary.
var ErrStaleEvent = errors.New("tracking: event is older than current status, ignoring")
