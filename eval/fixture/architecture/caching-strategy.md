# Caching strategy

## Overview

Wayfreight's public tracking page is, by request volume, the single busiest endpoint in the whole system - a haulier's customer refreshing "where's my pallet" every thirty seconds during a delivery window generates far more traffic than any internal dashboard. This note describes the three cache tiers that keep that endpoint fast without serving stale-enough data to be misleading, and the key naming conventions engineers should follow when adding a new cached value.

## Cache tiers

### CDN edge cache

The public tracking page (`/track/{trackingCode}`) sits behind CloudFront. Because the underlying ETA changes continuously, we deliberately keep the edge TTL short - 60 seconds - rather than trying to actively purge on every update. This bounds staleness to at most a minute without requiring any invalidation logic at all, which has proven far more reliable in practice than the alternative of pushing a purge on every `tracking_events` write.

### Application cache (Redis)

The same ElastiCache Redis cluster that backs the BullMQ job queue (see `adr-002-background-jobs-queue-vs-cron.md`) also serves as core-api's application-level cache, on a separate logical database index so a queue outage and a cache outage can be reasoned about independently even though they share hardware.

Two value types dominate:

- `track:eta:{consignmentId}` - the computed ETA for a consignment's next stop, TTL 90 seconds. Recomputed and re-cached whenever `recomputeEta()` runs, so the TTL mostly exists as a safety net against a missed invalidation rather than as the primary freshness mechanism.
- `haulier:profile:{haulierId}` - branding, contact details and notification preferences shown on the tracking page, TTL 24 hours, since this data changes rarely and a slightly stale support phone number is a much smaller problem than a stale ETA.

### In-process LRU cache

Each core-api process keeps a small in-memory LRU (capacity 10,000 entries) purely for rate-limit counters keyed by API key. This deliberately does not go through Redis: rate limiting is enforced per-process, which is slightly more permissive under Fargate autoscaling than a perfectly synchronised global counter would be, and that trade-off was judged acceptable because the limits exist to catch runaway clients, not to enforce hard billing quotas.

## Key naming convention

All Redis application-cache keys follow `{domain}:{entity}:{id}` (for example `track:eta:9f21ac`), which keeps `redis-cli --scan --pattern 'track:*'` useful for on-call debugging without needing to know a value's TTL or origin in advance. Keys never embed a version number; a cache-format change is handled by changing the prefix (`track:eta:v2:{id}`) so old and new formats can coexist during a rolling deploy.

## Cache stampede protection

When an ETA cache entry expires under heavy read load, a naive implementation lets every concurrent request recompute it simultaneously. We avoid this with a per-key mutex: the first request to miss the cache sets a short-lived lock key (`SET lock:track:eta:{id} 1 NX PX 500`) and computes the value; any request that finds the lock already held waits up to 500ms and retries the read rather than recomputing itself. In practice this keeps ETA recomputation to roughly one call per stop change rather than one call per concurrent tracking-page viewer.

## Cache hit rate target

We track application-cache hit rate on the Grafana caching dashboard and treat a sustained drop below 92% as worth investigating, since it usually indicates a TTL misconfiguration rather than genuine traffic pattern change.
