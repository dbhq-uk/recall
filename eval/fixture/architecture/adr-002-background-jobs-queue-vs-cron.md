---
status: accepted
date: 2024-11-20
deciders: S. Lindqvist, dispatch squad
---

# ADR 002: Background jobs - queue versus cron

## Status

Accepted.

## Context

Wayfreight has two shapes of background work that don't belong on the request/response path. The first is event-triggered and latency-sensitive: when a driver's app posts an arrival webhook, the consignment's ETA for every remaining stop on that route needs recomputing within a couple of seconds so the tracking page updates promptly. The second is purely time-based batch work: a nightly invoice run, a weekly driver compliance digest email. Early on we tried to force both shapes through a single mechanism and it fit neither well.

## Decision

Run two mechanisms side by side, chosen deliberately per job rather than by habit:

- **BullMQ**, backed by an ElastiCache Redis cluster, for event-triggered jobs. The driver-arrival webhook enqueues an `eta:recompute` job that a worker pool picks up and processes, calling `recomputeEta()` for every remaining stop on the route. We target and measure a 2-second service-level objective from webhook receipt to updated ETA being visible on the tracking page.
- **AWS EventBridge Scheduler** for fixed-time batch jobs: the nightly invoice run fires at 01:15 UTC, and the weekly driver compliance digest fires every Monday at 06:00 UTC. Each schedule target is a small Lambda that enqueues the actual work rather than doing it inline, so a slow batch job can't block the scheduler itself.

## Considered options

### Cron alone (rejected)

A single `node-cron` process, or system crontab entries, triggering scripts on a fixed schedule. This handles the nightly invoice run adequately but has no good answer for "recompute this ETA the moment this webhook arrives" short of polling on a very tight interval, which is wasteful and still adds latency roughly equal to half the poll period on average.

### A single queue for everything (rejected)

Using BullMQ exclusively, including for scheduled jobs, via its built-in repeatable job feature. This works but pushed scheduling logic and business logic into the same layer, and made it awkward to see, at a glance, "what fires on a fixed clock" without reading application code - operationally we wanted a scheduler that is legible from the AWS console, not just from the codebase.

### Hybrid: queue for events, scheduler for batch work (chosen)

Keeps each mechanism doing the thing it's good at. BullMQ gives us retries, backoff and per-job observability for event-triggered work; EventBridge Scheduler gives us a declarative, console-visible source of truth for anything that runs on a clock, independent of whether core-api happens to be healthy at that exact moment.

## Implementation notes

```yaml
# infra/schedules/nightly-invoice-run.yaml
ScheduleExpression: "cron(15 1 * * ? *)"   # 01:15 UTC, every day
Target:
  Arn: arn:aws:lambda:eu-west-2:xxxx:function:invoice-run-trigger
  RetryPolicy:
    MaximumRetryAttempts: 2
```

```bash
# checking recent BullMQ job outcomes for the eta:recompute queue
redis-cli --scan --pattern 'bull:eta:recompute:*' | head -20
```

## Consequences

Two systems to monitor instead of one, but each failure mode is now easy to reason about in isolation: a missed schedule shows up in EventBridge's own metrics, and a stuck queue shows up in the BullMQ dashboard we run alongside core-api. New engineers are told the rule of thumb directly: if a human or a webhook should be able to trigger it on demand, it's a queue job; if it only ever runs on a clock, it's a scheduled job.
