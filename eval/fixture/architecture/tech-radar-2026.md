# Engineering tech radar — 2026

## What this is

A one-page view of what Wayfreight engineering has adopted, what we are actively
trialling, what we are watching without commitment, and what we have decided
against. It is deliberately a pointer document: the reasoning behind anything in
the **Hold** ring lives in the ADR named against it, not here. If you want to
know *why* something was rejected, follow the link — do not infer it from the
ring it sits in.

Reviewed quarterly by the architecture group. Last review: 12 February 2026.

## Platform and data

| Item | Ring | Notes |
| --- | --- | --- |
| PostgreSQL 15 (RDS) | Adopt | Single primary, one reporting replica. |
| pgvector | Adopt | Incident similarity search. See ADR 004. |
| pg_cron | Adopt | In-database maintenance jobs on the core instance. |
| pg_stat_statements | Adopt | Feeds the Grafana slow-query panel. |
| postgis | Adopt | Depot catchment polygons. |
| ChromaDB | Hold | Considered and rejected for the incident embedding backend. See ADR 004. |
| Pinecone | Hold | Rejected alongside ChromaDB. See ADR 004. |
| Weaviate | Hold | Rejected alongside ChromaDB. See ADR 004. |
| dbmate | Adopt | Plain-SQL migrations. See the migration policy. |
| DynamoDB | Assess | No current use. Raised twice for tracking-event ingest and parked twice. |

A note on the vector row, because it comes up in nearly every architecture
onboarding conversation: the fact that ChromaDB sits in **Hold** does not mean it
is a bad tool. It means it was the wrong tool for the one problem we evaluated it
against. Somebody re-litigates this roughly every six months, usually after
reading a tutorial, and the answer is always "read ADR 004 first, then come
back". Nobody has come back yet.

## Jobs, queues and scheduling

| Item | Ring | Notes |
| --- | --- | --- |
| BullMQ | Adopt | Event-triggered work only. See ADR 002. |
| AWS EventBridge Scheduler | Adopt | Clock-triggered work only. See ADR 002. |
| node-cron | Hold | Rejected as the single mechanism for both shapes. See ADR 002. |
| Temporal | Assess | Interesting for long-running multi-step workflows. No pilot scheduled. |

The BullMQ / EventBridge split is the single most-asked-about line on this radar,
because on the surface both rings say "Adopt" for two things that look like they
overlap. They do not overlap; ADR 002 sets out the rule of thumb and the reasons
behind it, and the on-call queue runbook covers what to do when a BullMQ queue
backs up.

## Identity

| Item | Ring | Notes |
| --- | --- | --- |
| AWS Cognito | Adopt | Haulier web accounts. See ADR 003. |
| Twilio Verify | Adopt | Driver device enrolment. See ADR 003. |
| Auth0 | Hold | Rejected on per-MAU cost. See ADR 003. |
| Keycloak | Hold | Rejected as another stateful service to run. See ADR 003. |

## Runtime and delivery

| Item | Ring | Notes |
| --- | --- | --- |
| Node.js 20 + TypeScript | Adopt | core-api. |
| ECS Fargate | Adopt | One container image, one service. See ADR 001. |
| Microservices per domain | Hold | Rejected at launch. See ADR 001. Revisit around 25 engineers. |
| Lambda per endpoint | Hold | Rejected at launch. See ADR 001. |
| OpenTelemetry | Adopt | Traces to Honeycomb. |
| pino | Adopt | Structured JSON logs. |

## How to propose a change

Open a pull request against this file with the item, the proposed ring, and a
link to either an ADR or a written spike. Radar entries without one of those two
things are rejected on sight — the whole value of the radar is that every ring
placement is traceable to a decision somebody actually wrote down and defended,
rather than to whichever engineer argued hardest in a standup.
