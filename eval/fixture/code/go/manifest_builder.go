// Package manifest assembles the end-of-day carrier manifest and
// reconciles it against the shipment ledger before transmission.
//
// A manifest is the legal handoff document between us and a carrier:
// once sent, any parcel not on it is invisible to that carrier's
// systems, so we cross-check line by line first -- a mismatch here
// means a parcel physically on the truck with no paperwork trail.
package manifest

import (
	"errors"
	"fmt"
	"sort"
)

// MaxManifestLines caps shipments per manifest document; larger days
// split into multiple manifests.
const MaxManifestLines = 500

var ErrLedgerMismatch = errors.New("manifest: ledger reconciliation found discrepancies")
var ErrEmptyManifest = errors.New("manifest: refusing to transmit empty manifest")

// LedgerEntry is one shipment as recorded in the authoritative
// ledger, independent of the manifest builder's draft.
type LedgerEntry struct {
	ShipmentID string
	WeightKg   float64
	Committed  bool
}

// ManifestLine is one row printed on the driver's manifest document.
type ManifestLine struct {
	ShipmentID string
	WeightKg   float64
	Sequence   int
}

// Discrepancy describes one mismatch between draft and ledger.
type Discrepancy struct {
	ShipmentID string
	Reason     string
}

// ManifestBuilder accumulates manifest lines for one depot's
// end-of-day dispatch and reconciles them against the ledger.
type ManifestBuilder struct {
	DepotID string
	lines   []ManifestLine
}

// NewManifestBuilder starts an empty manifest for the given depot.
func NewManifestBuilder(depotID string) *ManifestBuilder {
	return &ManifestBuilder{DepotID: depotID, lines: make([]ManifestLine, 0)}
}

// AddShipment appends a shipment, refusing once the line cap is hit
// so oversized manifests get split by the caller.
func (b *ManifestBuilder) AddShipment(shipmentID string, weightKg float64) error {
	if len(b.lines) >= MaxManifestLines {
		return fmt.Errorf("manifest: depot %s is full at %d lines", b.DepotID, MaxManifestLines)
	}
	b.lines = append(b.lines, ManifestLine{
		ShipmentID: shipmentID,
		WeightKg:   weightKg,
		Sequence:   len(b.lines) + 1,
	})
	return nil
}

// TotalWeightKg sums the declared weight of every line on the draft.
func (b *ManifestBuilder) TotalWeightKg() float64 {
	total := 0.0
	for _, l := range b.lines {
		total += l.WeightKg
	}
	return total
}

// reconcileLedgerEntries returns every discrepancy in one pass rather
// than stopping at the first, so ops sees the whole picture at once.
func reconcileLedgerEntries(lines []ManifestLine, ledger map[string]LedgerEntry) []Discrepancy {
	var discrepancies []Discrepancy
	seen := make(map[string]bool)

	add := func(id, reason string) {
		discrepancies = append(discrepancies, Discrepancy{ShipmentID: id, Reason: reason})
	}

	for _, line := range lines {
		seen[line.ShipmentID] = true
		entry, ok := ledger[line.ShipmentID]
		if !ok {
			add(line.ShipmentID, "on manifest but not found in ledger")
			continue
		}
		if !entry.Committed {
			add(line.ShipmentID, "ledger entry exists but is not committed")
		}
		if entry.WeightKg != line.WeightKg {
			add(line.ShipmentID, fmt.Sprintf("weight mismatch: manifest=%.2f ledger=%.2f", line.WeightKg, entry.WeightKg))
		}
	}

	for id, entry := range ledger {
		if entry.Committed && !seen[id] {
			add(id, "committed in ledger but missing from manifest")
		}
	}

	sort.Slice(discrepancies, func(i, j int) bool {
		return discrepancies[i].ShipmentID < discrepancies[j].ShipmentID
	})
	return discrepancies
}

// FinalizeForTransmission returns the manifest lines only if the
// ledger and draft agree exactly, else ErrLedgerMismatch with details.
func (b *ManifestBuilder) FinalizeForTransmission(ledger map[string]LedgerEntry) ([]ManifestLine, []Discrepancy, error) {
	if len(b.lines) == 0 {
		return nil, nil, ErrEmptyManifest
	}
	discrepancies := reconcileLedgerEntries(b.lines, ledger)
	if len(discrepancies) > 0 {
		return nil, discrepancies, ErrLedgerMismatch
	}
	return b.lines, nil, nil
}
