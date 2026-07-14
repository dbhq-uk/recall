//! End-of-day reconciliation of the shipment ledger against
//! carrier billing.
//!
//! Carriers invoice weekly for whatever they think shipped, and it
//! rarely matches our numbers -- recalculated dimensional weight, an
//! unquoted surcharge, or a shipment billed twice by two hubs. This
//! is the arithmetic referee before anyone pays.

use std::collections::{HashMap, HashSet};

pub const MAX_ACCEPTABLE_VARIANCE_CENTS: i64 = 150;
pub const DISPUTE_THRESHOLD_CENTS: i64 = 5000;

#[derive(Debug, Clone)]
pub struct LedgerEntry { pub shipment_id: String, pub expected_cost_cents: i64 }

#[derive(Debug, Clone)]
pub struct CarrierInvoiceLine { pub shipment_id: String, pub billed_cost_cents: i64 }

#[derive(Debug, Clone, PartialEq)]
pub enum VarianceKind { WithinTolerance, Overcharge, Undercharge, MissingFromLedger, MissingFromInvoice }

#[derive(Debug, Clone)]
pub struct ReconciliationResult { pub shipment_id: String, pub kind: VarianceKind, pub variance_cents: i64 }

#[derive(Debug)]
pub enum ReconcileError { EmptyInvoice, DuplicateShipmentId(String) }

impl std::fmt::Display for ReconcileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptyInvoice => write!(f, "reconcile: invoice has no lines"),
            Self::DuplicateShipmentId(id) => write!(f, "reconcile: shipment {id} billed twice"),
        }
    }
}
impl std::error::Error for ReconcileError {}

/// Classifies every ledger entry against its invoice line; callers
/// need the full set, not just problems, to total exposure.
pub fn reconcile_ledger_entries(ledger: &[LedgerEntry], invoice: &[CarrierInvoiceLine])
    -> Result<Vec<ReconciliationResult>, ReconcileError> {
    if invoice.is_empty() {
        return Err(ReconcileError::EmptyInvoice);
    }
    let mut by_id = HashMap::new();
    for line in invoice {
        if by_id.insert(line.shipment_id.as_str(), line.billed_cost_cents).is_some() {
            return Err(ReconcileError::DuplicateShipmentId(line.shipment_id.clone()));
        }
    }
    let mut results = Vec::with_capacity(ledger.len());
    let mut seen = HashSet::new();
    for entry in ledger {
        seen.insert(&entry.shipment_id);
        let (kind, variance_cents) = match by_id.get(entry.shipment_id.as_str()) {
            None => (VarianceKind::MissingFromInvoice, entry.expected_cost_cents),
            Some(&billed) => {
                let v = billed - entry.expected_cost_cents;
                (classify_variance(v), v)
            }
        };
        results.push(ReconciliationResult { shipment_id: entry.shipment_id.clone(), kind, variance_cents });
    }
    for line in invoice {
        if !seen.contains(line.shipment_id.as_str()) {
            let kind = VarianceKind::MissingFromLedger;
            results.push(ReconciliationResult { shipment_id: line.shipment_id.clone(), kind, variance_cents: line.billed_cost_cents });
        }
    }
    Ok(results)
}

fn classify_variance(variance_cents: i64) -> VarianceKind {
    match variance_cents {
        v if v.abs() <= MAX_ACCEPTABLE_VARIANCE_CENTS => VarianceKind::WithinTolerance,
        v if v > 0 => VarianceKind::Overcharge,
        _ => VarianceKind::Undercharge,
    }
}

/// A running tally so the dispute desk watches exposure grow
/// instead of waiting on a batch job.
#[derive(Default)]
pub struct ExposureTracker {
    total_variance_cents: i64,
    disputed_ids: Vec<String>,
}

impl ExposureTracker {
    pub fn record(&mut self, result: &ReconciliationResult) {
        self.total_variance_cents += result.variance_cents;
        if result.variance_cents.abs() >= DISPUTE_THRESHOLD_CENTS {
            self.disputed_ids.push(result.shipment_id.clone());
        }
    }

    pub fn total_variance_cents(&self) -> i64 { self.total_variance_cents }

    pub fn should_escalate_to_disputes_team(&self) -> bool { !self.disputed_ids.is_empty() }

    pub fn disputed_ids(&self) -> &[String] { &self.disputed_ids }
}
