//! Handheld scanner protocol decoding for the depot receiving line.
//!
//! Scan guns talk to the gateway over a serial link using a compact
//! framed protocol, so it can tell scans apart from heartbeats and
//! low-battery warnings without parsing a string every time. This is
//! deliberately strict: a corrupted frame accepted as a scan posts a
//! phantom parcel to the receiving ledger.

pub const FRAME_START_BYTE: u8 = 0x02;
pub const FRAME_END_BYTE: u8 = 0x03;
pub const MAX_FRAME_LEN: usize = 64;
pub const SCANNER_HEARTBEAT_INTERVAL_SECS: u64 = 30;

#[derive(Debug, Clone, PartialEq)]
pub enum ScanEvent {
    Barcode { code: String, scanner_id: u8 },
    Heartbeat { scanner_id: u8, battery_pct: u8 },
    LowBattery { scanner_id: u8 },
}

#[derive(Debug, PartialEq)]
pub enum FrameError {
    TooShort, TooLong, MissingStartByte, MissingEndByte,
    ChecksumMismatch { expected: u8, actual: u8 },
    UnknownFrameKind(u8),
}

impl std::fmt::Display for FrameError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TooShort => write!(f, "scanner frame shorter than minimum valid length"),
            Self::TooLong => write!(f, "scanner frame exceeds MAX_FRAME_LEN"),
            Self::MissingStartByte => write!(f, "scanner frame missing start byte"),
            Self::MissingEndByte => write!(f, "scanner frame missing end byte"),
            Self::ChecksumMismatch { expected, actual } => write!(f, "checksum mismatch: expected {expected:#04x}, got {actual:#04x}"),
            Self::UnknownFrameKind(kind) => write!(f, "unrecognized frame kind {kind:#04x}"),
        }
    }
}
impl std::error::Error for FrameError {}

fn xor_checksum(bytes: &[u8]) -> u8 {
    bytes.iter().fold(0u8, |acc, b| acc ^ b)
}

/// Validates framing bytes and checksum before trusting the payload.
pub fn parse_frame(raw: &[u8]) -> Result<ScanEvent, FrameError> {
    if raw.len() < 5 { return Err(FrameError::TooShort); }
    if raw.len() > MAX_FRAME_LEN { return Err(FrameError::TooLong); }
    if raw[0] != FRAME_START_BYTE { return Err(FrameError::MissingStartByte); }
    if raw[raw.len() - 1] != FRAME_END_BYTE { return Err(FrameError::MissingEndByte); }
    let body = &raw[1..raw.len() - 2];
    let expected = raw[raw.len() - 2];
    let actual = xor_checksum(body);
    if expected != actual {
        return Err(FrameError::ChecksumMismatch { expected, actual });
    }
    let scanner_id = body[0];
    match body[1] {
        0x01 => Ok(ScanEvent::Barcode { code: String::from_utf8_lossy(&body[2..]).to_string(), scanner_id }),
        0x02 => Ok(ScanEvent::Heartbeat { scanner_id, battery_pct: *body.get(2).unwrap_or(&0) }),
        0x03 => Ok(ScanEvent::LowBattery { scanner_id }),
        other => Err(FrameError::UnknownFrameKind(other)),
    }
}

/// Buffers bytes off a serial connection and yields complete frames,
/// since a USB read can split or merge frames across chunks.
#[derive(Default)]
pub struct ScannerFrameBuffer {
    pending: Vec<u8>,
}

impl ScannerFrameBuffer {
    pub fn push_bytes(&mut self, chunk: &[u8]) {
        self.pending.extend_from_slice(chunk);
    }

    /// Leaves any trailing partial frame for the next chunk.
    pub fn drain_complete_frames(&mut self) -> Vec<Result<ScanEvent, FrameError>> {
        let mut results = Vec::new();
        loop {
            let Some(start) = self.pending.iter().position(|&b| b == FRAME_START_BYTE) else { break };
            let Some(offset) = self.pending[start..].iter().position(|&b| b == FRAME_END_BYTE) else { break };
            let end = start + offset;
            results.push(parse_frame(&self.pending[start..=end].to_vec()));
            self.pending.drain(0..=end);
        }
        results
    }

    pub fn pending_len(&self) -> usize {
        self.pending.len()
    }
}

/// Flags a scanner as offline rather than assume it's just between
/// scans.
pub fn is_scanner_overdue(seconds_since_last_event: u64) -> bool {
    seconds_since_last_event > SCANNER_HEARTBEAT_INTERVAL_SECS * 3
}
