# API versioning policy

## Overview

Wayfreight exposes two APIs with different versioning needs: a public partner API that third-party logistics software integrates against, and the internal API that core-api's own first-party web console and driver app consume. This note covers why they're versioned differently.

## Decision

The partner API is versioned in the URI path - `/v1/consignments`, `/v1/tracking-events` - and a breaking change always means a new path prefix (`/v2/...`) shipped alongside the old one, never a silent change to `/v1/`. The internal API carries no version at all; it is additive-only, changes deploy atomically with the clients that consume it (see `adr-001-modular-monolith.md`), and a "breaking" internal change is simply not permitted to ship without updating both sides in the same deploy.

## Considered alternatives

### Header-based versioning (rejected for the partner API)

Versioning via an `Accept: application/vnd.wayfreight.v2+json` header was seriously considered, since it keeps URLs stable and is arguably more RESTful. It was rejected for practical reasons specific to our partner integrators: several of the smaller haulage software vendors we work with test integrations by hand with curl or Postman, and a header is far easier to forget or get silently stripped by an intermediate proxy than a version that's visible in the URL every engineer on their side can see at a glance. Partner support tickets during the header-versioning trial period disproportionately involved someone unknowingly hitting the wrong version.

### No versioning anywhere, additive-only everywhere (rejected for the partner API)

This is what we do internally, and it was tempting to do everywhere to avoid maintaining two API surfaces in parallel. It doesn't work for the partner API because, unlike our own web console and driver app, we don't control partner deploy timing - a partner integration written against a field's current meaning can keep running unattended for years, so we can't guarantee an additive-only change is actually non-breaking from their point of view (adding a new required field, for instance, is additive in shape but breaking in practice).

## Deprecation policy

A partner API version is supported for a minimum of six months after the version that replaces it ships. During that window, responses from the deprecated version carry a `Sunset` HTTP header naming the date support ends, and the deprecation is separately announced in the partner developer changelog and by direct email to every registered partner integration contact - the header alone is not considered sufficient notice, since not every partner's client code surfaces response headers to a human.

```bash
# example response headers from a deprecated partner endpoint
curl -i https://api.wayfreight.com/v1/consignments/9f21ac
# HTTP/1.1 200 OK
# Sunset: Wed, 01 Oct 2025 00:00:00 GMT
# Link: <https://api.wayfreight.com/v2/consignments/9f21ac>; rel="successor-version"
```

## Consequences

Partner integrators get a stable, explicit contract they can plan migrations against; our own team avoids running two versions of the internal API in parallel, since that overhead only pays for itself when the two sides of an integration can't be deployed together, which is never true for our own first-party clients.
