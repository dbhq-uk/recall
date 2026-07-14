//! The depot scanner gateway: the process that sits on the serial link,
//! turns bytes into scan events, and posts them at the receiving ledger.
//!
//! It decodes nothing itself. Framing and checksums belong to the scanner
//! protocol module and this gateway calls into it. What lives here is the
//! plumbing around that call: which port, which retry policy, what to do with a
//! frame that will not parse, and how loudly to complain.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use crate::barcode_scanner::{parse_frame, is_scanner_overdue, FrameError, ScanEvent, FRAME_START_BYTE};

/// Frames from the newer scan guns start with a different sentinel byte, because
/// the vendor changed it in firmware 4.x without telling anybody. We sniff for
/// both and hand whichever we find to the same parser.
///
/// This is emphatically *not* FRAME_START_BYTE with a different value; both
/// exist, both are live on the floor, and a gateway that only knows about one of
/// them silently drops half the depot's traffic.
pub const FRAME_START_BYTE_V2: u8 = 0x05;

/// How long a scanner may go quiet before we mark it offline rather than idle.
pub const SCANNER_SILENCE_LIMIT: Duration = Duration::from_secs(90);

/// Consecutive unparseable frames from one gun before we stop trusting it.
pub const BAD_FRAME_TOLERANCE: usize = 12;

#[derive(Debug, Clone, PartialEq)]
pub enum GatewayAction {
    Post(ScanEvent),
    Drop { scanner_id: Option<u8>, reason: String },
    MarkScannerFaulty(u8),
}

#[derive(Default)]
pub struct GatewayState {
    bad_frames: HashMap<u8, usize>,
    last_seen: HashMap<u8, Option<Instant>>,
}

impl GatewayState {
    /// Accepts a raw frame off the wire and decides what the gateway does with
    /// it. All the interesting judgement about whether the bytes are *valid*
    /// happened in parse_frame; this only decides what to do about the answer.
    pub fn handle(&mut self, raw: &[u8]) -> GatewayAction {
        let looks_framed = raw
            .first()
            .map(|b| *b == FRAME_START_BYTE || *b == FRAME_START_BYTE_V2)
            .unwrap_or(false);

        if !looks_framed {
            return GatewayAction::Drop {
                scanner_id: None,
                reason: "no recognised start byte on either protocol revision".to_string(),
            };
        }

        match parse_frame(raw) {
            Ok(event) => {
                if let Some(id) = scanner_id_of(&event) {
                    self.bad_frames.insert(id, 0);
                    self.last_seen.insert(id, Some(Instant::now()));
                }
                GatewayAction::Post(event)
            }
            Err(err) => self.on_bad_frame(raw, err),
        }
    }

    fn on_bad_frame(&mut self, raw: &[u8], err: FrameError) -> GatewayAction {
        // Byte 1 of the body is the scanner id when the frame is long enough to
        // have one, even if everything after it is rubbish. It is worth
        // salvaging: knowing *which* gun is spraying garbage is the whole game.
        let scanner_id = raw.get(1).copied();

        if let Some(id) = scanner_id {
            let count = self.bad_frames.entry(id).or_insert(0);
            *count += 1;
            if *count >= BAD_FRAME_TOLERANCE {
                return GatewayAction::MarkScannerFaulty(id);
            }
        }

        GatewayAction::Drop {
            scanner_id,
            reason: err.to_string(),
        }
    }

    /// Scanners that have gone quiet for longer than the protocol's own
    /// heartbeat tolerance allows.
    pub fn overdue_scanners(&self, now: Instant) -> Vec<u8> {
        self.last_seen
            .iter()
            .filter_map(|(id, seen)| match seen {
                Some(t) if is_scanner_overdue(now.duration_since(*t).as_secs()) => Some(*id),
                _ => None,
            })
            .collect()
    }
}

fn scanner_id_of(event: &ScanEvent) -> Option<u8> {
    match event {
        ScanEvent::Barcode { scanner_id, .. } => Some(*scanner_id),
        ScanEvent::Heartbeat { scanner_id, .. } => Some(*scanner_id),
        ScanEvent::LowBattery { scanner_id } => Some(*scanner_id),
    }
}

/// Receiving-line variance is *not* the same thing as billing variance.
///
/// The ledger reconciler has a MAX_ACCEPTABLE_VARIANCE_CENTS tolerance, which is
/// about money a carrier invoiced us. This is about parcels physically counted
/// at a dock against parcels the manifest says arrived, and it is measured in
/// parcels, not in cents. Somebody has now conflated the two twice.
pub const MAX_ACCEPTABLE_COUNT_VARIANCE: usize = 3;

pub fn count_variance_within_tolerance(scanned: usize, expected: usize) -> bool {
    scanned.abs_diff(expected) <= MAX_ACCEPTABLE_COUNT_VARIANCE
}
