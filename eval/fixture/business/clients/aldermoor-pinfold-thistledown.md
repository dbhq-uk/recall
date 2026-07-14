---
title: Client notes — Aldermoor, Pinfold, Thistledown
tags: [clients, aldermoor, pinfold, thistledown]
---

# Client Notes: Aldermoor, Pinfold and Thistledown

Three smaller engagements that don't each warrant a full document on their own, but are worth keeping distinct rather than folding into the retrospective backlog and forgetting the detail.

## Aldermoor Health Partners

### Background

Aldermoor Health Partners run three private outpatient clinics across Somerset and Dorset, handling referrals that sit alongside NHS pathways rather than replacing them. They engaged us in mid-2025 to build a referral and case-management admin system to replace a mixture of a legacy Access database and email.

### Compliance requirements

Because Aldermoor handle patient data, the engagement carries a different weight to most of our client work, and it shaped how we scoped and staffed it from day one.

#### Working practices

We committed to working in a manner aligned with ISO 27001 — not certified ourselves, but following its control set for this engagement specifically: encrypted laptops, access logging on the staging and production environments, and a documented incident response process that Sam owns.

#### Data Processing Agreement

A Data Processing Agreement under UK GDPR was signed alongside the main contract, naming us as processor and Aldermoor as controller, with patient referral data as the special category data in scope. The DPA specifies a 72-hour breach notification window to Aldermoor, tighter than the statutory 72-hour ICO reporting clock, so that Aldermoor themselves have time to assess and report onward if needed.

### Staffing

Sam owns the incident response process and Priya led the build. Tom Vickers, our associate, joined the Phase 1 workstream in August 2025 and has been on it since, working mainly on the clinician assignment screens and the audit logging. He splits his week between this and our other retainer client.

Aldermoor's own onboarding and security clearance process is tied to Tom as a named individual, which has practical consequences for how the engagement is structured and how his time is billed. Those consequences, and the determination behind them, are recorded in the IR35 notes — not here, and not in the contract folder summary. This document records only that he works on it.

### Scope and value

Phase 1 (referral intake, case notes, clinician assignment) was quoted at £120,000, delivered across five months from July to November 2025. Phase 2 (patient-facing appointment booking) is in discovery as of this writing, expected to be scoped as a separate fixed-price engagement once Aldermoor's board signs off budget in their next financial year.

### How it's gone

Genuinely one of the better-run projects we've had, in large part because Aldermoor assigned a single clinical lead (a practice manager, not a clinician, which matters — she has authority to make decisions without convening a committee every time) as our point of contact. The trade-off is pace: every release goes through a change-control step on their side that we don't control, which has meant our usual two-week release cadence stretching to three or four weeks in practice. We've built that into how we plan the retainer-style Phase 2 discussions rather than fighting it.

## Pinfold Brewing Co

Pinfold Brewing Co is a nine-person brewery in Frome, and this was about as smooth a small engagement as we've run. They needed their point-of-sale system (a standard product called Epos Now, used in their taproom) talking to their existing stock and cask-tracking spreadsheet, so that a keg sold at the bar decremented the same inventory count their brewer used for production planning.

We found them, or rather they found us, at the West of England Tech Summit in October 2024 — the brewery's owner was on a panel about local supply chains and got chatting to Alex on a coffee break. They signed in November 2024 and we delivered the integration as a fixed-price job, £14,500, in February 2025, on time and without a single change order. They've since become a reliable source of word-of-mouth referrals in the Frome business community, though nothing has converted yet.

## Thistledown Legal

A cautionary one. Thistledown Legal, a small conveyancing and family law firm in Bath, approached us in December 2025 wanting a document management system to replace a shared drive that had become unmanageable — duplicate filenames, no version history, partners emailing PDFs back and forth.

We spent three months in scoping conversations, building toward what would have been a roughly £45,000 fixed-price engagement, before the deal collapsed in March 2026. The reason, when it came out, was straightforward: their incumbent legal-tech vendor, on hearing they were shopping around, offered to match our quote for a bolt-on module that did most of what we'd scoped, and the partners — three of them, all needing to agree — decided the risk of switching platforms outweighed the benefit of a better-fitting but unfamiliar system. Nothing we could have done differently on price; it came down to switching cost and risk appetite in a profession that's structurally cautious about exactly that. Worth remembering next time we're up against an incumbent in a regulated trade: the pitch needs to address switching risk explicitly, not just capability.
