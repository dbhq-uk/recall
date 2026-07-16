---
status: accepted
date: 2024-09-02
deciders: R. Okafor, founding engineering team
---

# ADR 001: Modular monolith over microservices at launch

## Status

Accepted.

## Context

At the point this decision was made, Wayfreight had six engineers and roughly four months of runway before the promised MVP demo to our first haulier customer: onboarding, consignment creation, driver dispatch, live tracking and invoicing all had to exist, end to end, by then. Several of the team had come from organisations running twenty-plus microservices and were wary of repeating that experience with a team a fraction of the size - a lot of that time is service scaffolding, cross-service contract negotiation and distributed debugging rather than product work.

## Decision

Build one deployable service, `core-api`, in Node.js 20 with TypeScript, organised internally into four bounded modules: `dispatch`, `tracking`, `billing` and `notifications`. Each module owns its own directory, its own Postgres schema namespace, and exposes a single `index.ts` as the only file other modules are permitted to import from. We enforce that boundary at build time with `eslint-plugin-boundaries`, so a pull request that has `billing` reach directly into `tracking`'s internal files fails CI with a lint error rather than being caught in review. The whole service deploys as one container image to ECS Fargate.

## Considered options

### Microservices per domain (rejected)

Splitting `dispatch`, `tracking`, `billing` and `notifications` into four independently deployable services from day one. This was rejected primarily on team-size grounds: four services means four deploy pipelines, four sets of infrastructure to provision, and cross-service calls (does `billing` call `tracking` synchronously or via an event?) that have to be designed correctly before we even know the shape of the domain. With six engineers, most weeks would have more people maintaining service boundaries than writing the tracking and dispatch logic that the business actually needed validated. We also expected the module boundaries themselves to shift substantially in the first few months, which is expensive to do across service boundaries and cheap to do inside a single codebase.

### Serverless functions per endpoint (rejected)

Each API route as its own Lambda function, on the theory that scaling and deployment become "somebody else's problem." Rejected because our access patterns include several endpoints doing multi-table transactional writes (consignment creation touches `dispatch`, `billing` and `notifications` in one request) which map poorly onto short-lived, independently-scaled functions, and because local development and debugging across dozens of functions was judged worse for a small team than a single process you can attach a debugger to.

### Modular monolith (chosen)

Gives us most of the benefit people actually want from microservices - enforced boundaries, the ability to reason about one module at a time, the option to extract a module later - without paying the operational tax before we have enough engineers to carry it. Because the module boundary is already expressed as a public TypeScript interface rather than an implementation detail, extracting a module into its own service later is a mechanical exercise: stand up the new service behind the existing `index.ts` contract, then swap the in-process import for a network call.

## Consequences

One CI pipeline, one deployment, and one set of logs to correlate during an incident - see `build-ci-pipeline.md` and `observability-and-logging.md` for how each of those actually works day to day. The team agreed to revisit this decision once headcount passes roughly 25 engineers, or sooner if a single module's scaling needs diverge sharply from the rest. The leading candidate for an early split is `tracking`, which ingests a GPS ping from every active driver roughly every fifteen seconds and is already the module with the most distinct load profile from the other three.
