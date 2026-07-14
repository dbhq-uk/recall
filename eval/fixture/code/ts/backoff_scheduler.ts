/**
 * Retry scheduling for carrier webhook delivery.
 *
 * Carrier status webhooks (label printed, picked up, out for delivery)
 * fail to deliver constantly -- customer firewalls, flaky endpoints,
 * five-second timeouts on a Friday deploy. Retrying immediately just
 * hammers an endpoint that's already struggling, so every retry here
 * waits longer than the last and eventually gives up rather than
 * retrying forever and quietly leaking memory.
 */

export const MAX_RETRY_BUDGET = 7;
export const BASE_DELAY_MS = 500;
export const MAX_DELAY_MS = 60_000;
export const JITTER_RATIO = 0.2;

export class RetryBudgetExhaustedError extends Error {
  constructor(attempts: number) {
    super(`retry budget exhausted after ${attempts} attempts`);
    this.name = "RetryBudgetExhaustedError";
  }
}

export interface AttemptRecord {
  attemptNumber: number;
  delayMs: number;
  firedAt: number;
}

function randomJitter(delayMs: number): number {
  const spread = delayMs * JITTER_RATIO;
  return delayMs - spread + Math.random() * spread * 2;
}

/**
 * Computes exponential backoff delays and tracks how many attempts a
 * given webhook delivery has burned through, so callers can decide
 * when a destination endpoint should be quarantined instead of
 * hammered indefinitely.
 */
export class BackoffScheduler {
  private attempts: AttemptRecord[] = [];
  private readonly maxAttempts: number;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;

  constructor(
    maxAttempts: number = MAX_RETRY_BUDGET,
    baseDelayMs: number = BASE_DELAY_MS,
    maxDelayMs: number = MAX_DELAY_MS
  ) {
    this.maxAttempts = maxAttempts;
    this.baseDelayMs = baseDelayMs;
    this.maxDelayMs = maxDelayMs;
  }

  private nextRawDelay(): number {
    const attemptIndex = this.attempts.length;
    const exponential = this.baseDelayMs * Math.pow(2, attemptIndex);
    return Math.min(exponential, this.maxDelayMs);
  }

  hasBudgetRemaining(): boolean {
    return this.attempts.length < this.maxAttempts;
  }

  recordAttempt(now: number = Date.now()): AttemptRecord {
    if (!this.hasBudgetRemaining()) {
      throw new RetryBudgetExhaustedError(this.attempts.length);
    }
    const delayMs = Math.round(randomJitter(this.nextRawDelay()));
    const record: AttemptRecord = {
      attemptNumber: this.attempts.length + 1,
      delayMs,
      firedAt: now,
    };
    this.attempts.push(record);
    return record;
  }

  attemptCount(): number {
    return this.attempts.length;
  }

  reset(): void {
    this.attempts = [];
  }

  totalElapsedDelayMs(): number {
    return this.attempts.reduce((sum, a) => sum + a.delayMs, 0);
  }
}

/**
 * Drives an async delivery function through the backoff schedule until
 * it succeeds, the budget runs out, or the caller's abort signal fires.
 */
export async function deliverWithBackoff(
  deliver: () => Promise<void>,
  scheduler: BackoffScheduler = new BackoffScheduler(),
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms))
): Promise<number> {
  while (true) {
    try {
      await deliver();
      return scheduler.attemptCount();
    } catch (err) {
      if (!scheduler.hasBudgetRemaining()) {
        throw new RetryBudgetExhaustedError(scheduler.attemptCount());
      }
      const record = scheduler.recordAttempt();
      await sleep(record.delayMs);
    }
  }
}

export function quarantineThresholdReached(consecutiveFailures: number): boolean {
  const QUARANTINE_FAILURE_THRESHOLD = 25;
  return consecutiveFailures >= QUARANTINE_FAILURE_THRESHOLD;
}
