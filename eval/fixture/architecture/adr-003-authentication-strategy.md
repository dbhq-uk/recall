---
status: accepted
date: 2024-10-05
deciders: R. Okafor, security working group
---

# ADR 003: Authentication strategy

## Status

Accepted.

## Context

Wayfreight has two distinct populations that need to authenticate, with very different constraints. Haulier back-office staff use a web console from a browser and expect the usual patterns: email/password, SSO for larger accounts, password reset flows. Drivers use a mobile app in a van, frequently with poor signal, and re-typing a password every time a session expires is a real complaint we heard in early pilots. We needed a decision that served both without building two entirely separate identity systems.

## Decision

Haulier web accounts authenticate against **AWS Cognito**. On sign-in, core-api exchanges the Cognito session for a short-lived JWT access token (15 minutes) and a refresh token that rotates on every use and is valid for 30 days; rotation means a stolen refresh token only has a single use window before the legitimate client's next refresh invalidates it. The `COGNITO_USER_POOL_ID` environment variable configures which pool core-api validates tokens against per deployment environment.

Drivers authenticate differently: on first install, the app verifies the driver's phone number via **Twilio Verify** (an SMS one-time code), and on success core-api issues a long-lived, device-bound API key stored in the device's secure enclave rather than a session that expires on a timer. This trades a small amount of security surface (a lost phone means a key to revoke) for drivers never having to re-authenticate mid-shift, which was judged the right trade-off given the operating environment.

Service-to-service calls within core-api's own infrastructure - for example the embedding worker calling back into core-api - use a separate, rotated shared secret held in `WAYFREIGHT_SERVICE_JWT_SECRET`, kept entirely distinct from customer-facing credentials so a leak in one system can't be used to forge the other.

## Considered options

### Auth0 (rejected)

Auth0 was the incumbent favourite going in, largely on developer-experience grounds. It was rejected on cost: Auth0's per-monthly-active-user pricing, projected against our forecast of roughly 40,000 haulier MAU within the first eighteen months, came out meaningfully more expensive than Cognito, and Wayfreight already runs entirely on AWS, so Cognito added no new vendor relationship to manage.

### Self-hosted Keycloak (rejected)

Keycloak would have avoided both platform lock-in and per-MAU pricing, but it is itself a stateful service that needs a database, a cache and its own high-availability story to run safely in production - exactly the kind of extra stateful service the team has independently tried to avoid elsewhere in the architecture (compare the reasoning against a self-hosted vector database in `adr-004-vector-store.md`, arrived at separately but for the same underlying reason: every additional stateful service is an additional on-call burden for a small team).

### One scheme for both populations (rejected)

Forcing drivers through the same Cognito-and-refresh-token flow as web users was tried in an early prototype and abandoned after driver pilot feedback specifically cited repeated re-logins as a source of frustration during a shift; the device-bound API key approach removed that friction entirely.

## Consequences

Two authentication code paths to maintain instead of one, but each is tuned to how that population actually uses the product. A compromised driver device is revoked by deleting its API key server-side; a compromised haulier session expires naturally within 15 minutes even if the refresh token is never explicitly revoked.
