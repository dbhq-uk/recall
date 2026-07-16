---
title: Rate card 2026
tags: [finance, pricing, rate-card]
---

# Rate Card — Effective 1 January 2026

## Day rates

- Junior / associate developer: £450/day (was £420 in 2025, +7%)
- Senior developer / tech lead: £650/day (was £600, +8%)
- Discovery, architecture, consulting: £850/day (was £780, +9%)

The increases track a mix of general inflation, rising software licence costs, and the fact that the renewal of our professional indemnity cover this year came in higher again — none of these individually would justify an 8-9% jump, but together they made holding 2025's rates unviable.

## Fixed price policy

Any fixed-price quote is built from an internal estimate in developer-days at the relevant day rate, then multiplied by 1.4 as a risk buffer before it's presented to the client. This isn't padding for its own sake — it's what the Bramwell & Foss retrospective, among others, has taught us about how often "should take three weeks" becomes four and a half once you're inside a client's actual systems. Anything we can't estimate with reasonable confidence gets scoped as time-and-materials instead, full stop, no matter how much a client would prefer a fixed number.

## Kestrel Launchpad

Launched Q1 2026: a productised, fixed-scope offering for early-stage companies who want a working MVP without a bespoke discovery process. Six weeks, fixed price £18,000, a defined menu of technical choices (Next.js frontend, a small set of pre-approved backend stacks, standard auth and payments integrations) rather than a blank slate. The point is to remove the discovery-and-negotiation overhead that eats margin on small fixed-price jobs, by pre-deciding as much as we sensibly can.

## Discounting policy

We don't discount day rates. Where a prospective client's budget doesn't stretch to the scope they want, the conversation is about reducing scope, not reducing rate — cutting rate on one engagement makes the next rate conversation with that client, or with anyone who hears about it, harder than it needs to be. The one standing exception is a returning-client discount: 5% off day rate for any client on their second engagement within eighteen months of the first, as a small thank-you for not making us re-sell ourselves from scratch.

## Retainer pricing

Retainers are priced as a guaranteed day allocation per month rather than a discounted day rate — see the Northgate engagement notes for how that works in practice. We've found clients prefer certainty of cost over a marginal per-day saving, and it suits us better too: a retainer smooths our own capacity planning in a way that a string of one-off projects doesn't.

## Example rate calculation

Quick reference script for turning an estimate into a fixed-price number without doing the arithmetic by hand each time:

```bash
#!/usr/bin/env bash
# quote-calc.sh — rough fixed-price quote from an estimate in developer-days
# Usage: ./quote-calc.sh <days> <rate>
days=$1
rate=$2
# Apply the standard 1.4x risk buffer for fixed-price work
python3 -c "print(f'{$days * $rate * 1.4:.2f}')"
```

## Review cadence

Rates are reviewed every January against the previous year's actuals — realised margin per engagement type, not just cost inflation — rather than on an ad hoc basis mid-year. The one exception would be a genuinely exceptional cost shock; nothing so far has qualified.
