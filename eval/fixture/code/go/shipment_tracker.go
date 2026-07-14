// Package tracking maintains the authoritative state machine for a
// shipment moving from booking through final delivery.
//
// Status updates arrive out of order constantly: a depot scan can
// reach ingestion after the "delivered" webhook, since they travel
// over different networks with wildly different latency. This file
// stops those races from corrupting a shipment's recorded history.
package tracking

import (
	"errors"
	"fmt"
	"time"
)

// Status represents where a shipment sits in its lifecycle.
type Status int

const (
	StatusBooked Status = iota
	StatusPickedUp
	StatusInTransit
	StatusOutForDelivery
	StatusDelivered
	StatusException
)

var statusNames = [...]string{"booked", "picked_up", "in_transit", "out_for_delivery", "delivered", "exception"}

func (s Status) String() string {
	if int(s) < len(statusNames) {
		return statusNames[s]
	}
	return "unknown"
}

// ErrStaleEvent means the event's timestamp precedes the shipment's
// currently recorded status update.
var ErrStaleEvent = errors.New("tracking: event is older than current status, ignoring")

// ErrTerminalStatus means the shipment already reached a terminal status.
var ErrTerminalStatus = errors.New("tracking: shipment already in a terminal status")

// legalTransitions: a jump from "booked" to "delivered" means a
// dropped scan, not a teleporting package.
var legalTransitions = map[Status][]Status{
	StatusBooked:         {StatusPickedUp, StatusException},
	StatusPickedUp:       {StatusInTransit, StatusException},
	StatusInTransit:      {StatusOutForDelivery, StatusException},
	StatusOutForDelivery: {StatusDelivered, StatusException},
}

// StatusEvent is a timestamped update from a carrier, driver app, or
// depot scan.
type StatusEvent struct {
	Status     Status
	OccurredAt time.Time
	Source     string
}

// ShipmentTracker holds one shipment's state and full event history.
type ShipmentTracker struct {
	ShipmentID string
	Current    Status
	LastEventAt time.Time
	History    []StatusEvent
}

// NewShipmentTracker creates a tracker in the initial booked state.
func NewShipmentTracker(shipmentID string, bookedAt time.Time) *ShipmentTracker {
	first := StatusEvent{Status: StatusBooked, OccurredAt: bookedAt, Source: "booking-api"}
	return &ShipmentTracker{ShipmentID: shipmentID, Current: StatusBooked, LastEventAt: bookedAt, History: []StatusEvent{first}}
}

func isTerminal(s Status) bool {
	return s == StatusDelivered || s == StatusException
}

func isLegalTransition(from, to Status) bool {
	for _, allowed := range legalTransitions[from] {
		if allowed == to {
			return true
		}
	}
	return false
}

// ApplyEvent rejects stale or illegal transitions.
func (t *ShipmentTracker) ApplyEvent(event StatusEvent) error {
	if isTerminal(t.Current) {
		return fmt.Errorf("%w: shipment %s is %s", ErrTerminalStatus, t.ShipmentID, t.Current)
	}
	if event.OccurredAt.Before(t.LastEventAt) {
		return fmt.Errorf("%w: shipment %s event at %s before current %s",
			ErrStaleEvent, t.ShipmentID, event.OccurredAt, t.LastEventAt)
	}
	if !isLegalTransition(t.Current, event.Status) {
		return fmt.Errorf("tracking: illegal transition %s -> %s for shipment %s",
			t.Current, event.Status, t.ShipmentID)
	}
	t.Current = event.Status
	t.LastEventAt = event.OccurredAt
	t.History = append(t.History, event)
	return nil
}

// TimeInStatus feeds the "delayed shipment" alerting job.
func (t *ShipmentTracker) TimeInStatus(now time.Time) time.Duration {
	return now.Sub(t.LastEventAt)
}

// IsOverdue flags shipments stuck in a non-terminal status past SLA.
func (t *ShipmentTracker) IsOverdue(now time.Time, sla time.Duration) bool {
	if isTerminal(t.Current) {
		return false
	}
	return t.TimeInStatus(now) > sla
}

// EventsFromSource filters history to one integration's events.
func (t *ShipmentTracker) EventsFromSource(source string) []StatusEvent {
	var matched []StatusEvent
	for _, e := range t.History {
		if e.Source == source {
			matched = append(matched, e)
		}
	}
	return matched
}
