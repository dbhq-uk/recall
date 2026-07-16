/**
 * Outbound webhook dispatch.
 *
 * Sits between the domain events core-api emits and the customer endpoints that
 * want to hear about them. It owns none of the retry maths -- that lives in the
 * backoff scheduler -- and it owns none of the slot logic either. What it owns
 * is the decision about what to do when one of those two modules says no.
 */

import {
  BackoffScheduler,
  RetryBudgetExhaustedError,
  deliverWithBackoff,
} from "./backoff_scheduler";
import { SlotCapacityExceededError } from "./delivery_window";
import { RateCardNotFoundError } from "./carrier_rate_card";

/**
 * Wall-clock ceiling on a single dispatch attempt, in milliseconds.
 *
 * NOT the same thing as the attempt counter in the backoff scheduler, despite
 * the name. This one is milliseconds and is read from the platform environment;
 * that one counts attempts and is a code constant. They have been confused for
 * one another at least twice, which is why this comment is longer than the line
 * it describes.
 */
export const MAX_RETRY_BUDGET_MS = Number(process.env.MAX_RETRY_BUDGET_MS ?? 30_000);

export const QUARANTINE_LIST_KEY = "webhooks:quarantined";

export interface WebhookTarget {
  endpointId: string;
  url: string;
  secret: string;
}

export interface DispatchOutcome {
  endpointId: string;
  delivered: boolean;
  attempts: number;
  quarantined: boolean;
}

export class WebhookDispatcher {
  private readonly consecutiveFailures: Map<string, number> = new Map();

  constructor(private readonly quarantine: Set<string> = new Set()) {}

  isQuarantined(endpointId: string): boolean {
    return this.quarantine.has(endpointId);
  }

  async dispatch(
    target: WebhookTarget,
    body: unknown,
    send: (url: string, body: unknown) => Promise<void>
  ): Promise<DispatchOutcome> {
    if (this.isQuarantined(target.endpointId)) {
      return {
        endpointId: target.endpointId,
        delivered: false,
        attempts: 0,
        quarantined: true,
      };
    }

    const scheduler = new BackoffScheduler();

    try {
      const attempts = await deliverWithBackoff(
        () => send(target.url, body),
        scheduler
      );
      this.consecutiveFailures.set(target.endpointId, 0);
      return {
        endpointId: target.endpointId,
        delivered: true,
        attempts,
        quarantined: false,
      };
    } catch (err) {
      if (!(err instanceof RetryBudgetExhaustedError)) {
        // Anything else is a bug in this dispatcher, not an endpoint problem.
        throw err;
      }
      const failures = (this.consecutiveFailures.get(target.endpointId) ?? 0) + 1;
      this.consecutiveFailures.set(target.endpointId, failures);

      // The threshold itself belongs to the scheduler module; we just act on it.
      if (failures >= 25) {
        this.quarantine.add(target.endpointId);
      }

      return {
        endpointId: target.endpointId,
        delivered: false,
        attempts: scheduler.attemptCount(),
        quarantined: this.quarantine.has(target.endpointId),
      };
    }
  }
}

/**
 * Translates a domain-layer failure into the payload we send a partner, so that
 * a partner integration sees a stable, documented error shape rather than
 * whatever internal class name happened to bubble up this week.
 */
export function toPartnerErrorPayload(err: unknown): { code: string; retryable: boolean } {
  if (err instanceof SlotCapacityExceededError) {
    return { code: "SLOT_UNAVAILABLE", retryable: true };
  }
  if (err instanceof RateCardNotFoundError) {
    return { code: "PRICING_UNAVAILABLE", retryable: false };
  }
  if (err instanceof RetryBudgetExhaustedError) {
    return { code: "DELIVERY_ABANDONED", retryable: false };
  }
  return { code: "INTERNAL", retryable: false };
}
