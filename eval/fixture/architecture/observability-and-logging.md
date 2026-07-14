# Observability and logging

## Overview

core-api emits three kinds of telemetry - structured logs, metrics, and traces - and this note is the map of where each one goes and how an engineer follows a single request through all three during an incident.

## Structured logging

All application logs are JSON, emitted via **pino** rather than a plain `console.log`, so every log line is machine-parseable without a regex. Every request is tagged with the value of its `x-request-id` header (generated at the ALB if the client didn't supply one), and that value is threaded through every log line emitted while handling that request, including lines written from background jobs that request triggered. Finding everything that happened for one troublesome tracking-page load is therefore a single query for one `x-request-id` value, not a time-range guess.

Log levels follow a strict rule: `error` means a human needs to look at this before the next deploy, `warn` means something recovered but shouldn't have happened, and `info` is for business events (consignment created, driver assigned) rather than debugging detail, which lives at `debug` and is disabled in production. An example error log line looks like:

```json
{"level":"error","msg":"consignment locked by another dispatcher","code":"ERR_CONSIGNMENT_LOCKED","requestId":"a1b2c3","consignmentId":"9f21ac"}
```

Logs are shipped to CloudWatch Logs and retained for 30 days, which is long enough to investigate any incident reported through normal support channels without keeping indefinite history of driver location data.

## Metrics

Application and infrastructure metrics are scraped by Prometheus and visualised in Grafana, including the query-performance dashboard described in `postgres-extensions.md`, which reads from `pg_stat_statements` rather than from application metrics directly.

## Tracing

Distributed traces use OpenTelemetry, with spans exported to Honeycomb as the backend. Every core-api process is configured with the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable pointing at a local collector sidecar, which batches and forwards spans rather than each process talking to Honeycomb directly. A trace for a single tracking-page request typically shows the HTTP span, the Redis cache lookup described in `caching-strategy.md`, and, on a cache miss, the Postgres query span beneath it - enough to see at a glance which tier is responsible for a slow response.

```yaml
# otel-collector-config.yaml (sidecar)
receivers:
  otlp:
    protocols:
      grpc:
      http:
exporters:
  otlp/honeycomb:
    endpoint: "api.honeycomb.io:443"
    headers:
      # team-scoped write key, injected from Secrets Manager at deploy time
      "x-honeycomb-team": "${HONEYCOMB_API_KEY}"
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp/honeycomb]
```

## Alerting

Alerts route through PagerDuty. Paging alerts are deliberately few and all tied to customer-visible symptoms - elevated error rate, elevated latency, a stalled BullMQ queue - rather than to internal signals like CPU usage, on the theory that an on-call engineer should only be woken for something a customer would notice.

## Querying logs

```bash
# find every log line for one troublesome request
aws logs start-query \
  --log-group-name /ecs/core-api \
  --start-time $(date -d '2 hours ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, msg | filter requestId = "a1b2c3"'
```

## Service level objectives

core-api's SLO is p99 latency under 400ms for the tracking-page read path, measured over a rolling 30-day window, with an error budget of 0.1% of requests. Burning through more than half the monthly error budget in under a week triggers an automatic Slack notification to the on-call channel, ahead of the budget being fully exhausted.
