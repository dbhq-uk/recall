---
title: Bramwell & Foss — e-commerce rebuild retrospective
tags: [clients, retrospective, ecommerce, bramwell-foss]
client: Bramwell & Foss
status: closed
---

# Bramwell & Foss — Engagement Retrospective

Bramwell & Foss is a bathroom fittings and sanitaryware retailer based in Chippenham, trading online and through two showrooms. They came to us in February 2025 wanting to move off a five-year-old Shopify Plus theme onto something they could extend themselves without paying the Shopify app-store tax on every feature.

## Background

Owner Marcus Foss inherited the business from his father in 2022 and was frustrated that a simple change — adding a "notify me when back in stock" flow — meant a monthly app subscription plus a developer to configure it. He wanted a custom storefront with full control over checkout and product data, backed by a headless CMS so the marketing team could publish without touching code.

We scoped a Next.js storefront against a headless Shopify backend (keeping Shopify for inventory and fulfilment, dropping the theme layer entirely), with Sanity as the content layer for landing pages and buying guides.

## Scope and delivery

### Original scope

Fixed price of £62,000, agreed 14 February 2025, four-month timeline targeting a go-live at the end of June. Payment schedule: 30% on signature, 30% at design sign-off, 40% on go-live.

### Scope creep: the Klarna integration

In week six Marcus asked, almost as an aside, whether we could "just add Klarna, our showroom customers keep asking." Shopify's native checkout doesn't expose Klarna in a headless setup without Checkout Extensibility, which we hadn't scoped and which was still maturing at the time. We agreed a change order for an extra £9,200 rather than trying to absorb it, which was the right financial call but cost five weeks of calendar time we hadn't planned for, because Priya was the only one who'd touched Checkout Extensibility and she was half-seconded to Northgate at the time.

## What went wrong

The honest retro: we should have asked "what else are you assuming is in scope?" explicitly in the kickoff, rather than relying on the statement of work to do that job for us. Marcus wasn't being difficult — from his side, "add a payment method" sounds small, and nobody on our side flagged early that Shopify's headless checkout is a walled garden until you hit its edges. That's on us, not him.

The bigger problem was resourcing, not scoping. We run lean enough that a single specialist becomes a hard dependency the moment something unusual comes up, and we had no slack to pull someone else onto Checkout Extensibility without hurting Northgate's delivery schedule in the same window. The project overran by six weeks against the original date, landing on 8 August instead of the end of June. Marcus was understanding because we were transparent early rather than the week before go-live, but it ate our margin: the change order fee roughly covered the extra engineering time and not much else.

We also under-priced discovery. Two days isn't enough for a business with three years of ad-hoc Shopify app configuration to unpick; we found undocumented logic — a custom shipping rate calculator bolted on via a third-party app, no documentation, departed original author — three weeks into build, when it should have surfaced in week one. Untangling it added four unbilled days before we could even scope the change order properly.

A fixed quote is only as good as the discovery underpinning it, and on migration work specifically we've been pricing discovery as a formality rather than the part of the job most likely to contain the actual risk.

## What we'd do differently

- Explicit "what's NOT in scope" list in the statement of work, not just what is.
- Minimum one week of paid technical discovery on any migration off an existing platform, priced and delivered separately, before a fixed-price quote is issued.
- No single-specialist dependencies on fixed-price work without a named backup, even if that backup is just a day of reading-in before the contract is signed.

## Deployment notes

Final release process, for reference (Priya wrote most of this):

```bash
#!/usr/bin/env bash
# deploy-storefront.sh — Bramwell & Foss production release
# Run from the storefront repo root after CI is green.
set -euo pipefail

# 1. Build against the production Shopify Storefront API token
npm run build -- --env=production

# 2. Purge the Sanity CDN cache so new landing pages show immediately
curl -X POST "$SANITY_PURGE_HOOK"

# 3. Deploy to Vercel and promote to production alias
vercel deploy --prod --token="$VERCEL_TOKEN"
```

## How the change order was priced

For the record, since it comes up whenever anyone reads this retro: the £9,200 Klarna change order was built the same way any of our fixed-price work is, from an internal estimate in developer-days at the senior day rate with the standard 1.4x risk buffer applied on top. The rate card explains what that multiplier exists for; this note is not the place to re-argue it.

What is worth saying here is only what the buffer failed to cover, which was calendar time. Whatever that multiplier exists to absorb — and the rate card is the document that sets that out, not this one — it plainly did not absorb five weeks of a client's go-live sliding, nor the opportunity cost of the one person capable of doing the work being unavailable to do anything else for the duration. Those are not estimation errors and no multiplier fixes them.

## Numbers

Total billed across the engagement: £71,200 (£62,000 base plus the £9,200 Klarna change order). Final milestone invoice KSW-2025-0143, £34,000, raised 12 August 2025 and paid 21 August — Bramwell & Foss have never once been late on an invoice, which counts for a lot given how the timeline went.
