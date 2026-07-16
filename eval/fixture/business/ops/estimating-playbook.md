---
title: Estimating playbook
tags: [ops, estimating, delivery, process]
---

# Estimating Playbook

How we turn a client's description of what they want into a number of
developer-days. This is the mechanical process; it deliberately stops short of
pricing. What we do with the day count afterwards — the day rate applied, the 1.4x
risk buffer, whether it becomes a fixed price at all — is set out in the rate
card, and the rate card is the place to argue about it. This document is only
about producing an honest day count in the first place.

## Who estimates

Two people, independently, always. Never one, and never a group in a room, because
a group converges on whatever the most senior person said first. The two estimates
are compared before either estimator sees the other's number.

If the two estimates are within 20% of each other, take the higher one and move
on. If they are more than 20% apart, that gap is information: it almost always
means the two of you are imagining different scopes, and the conversation about
*why* you differ is worth more than the estimate itself. Resolve the scope
question, then re-estimate.

## The unit

Developer-days. Not story points, not hours, not weeks.

- Not hours, because nobody works an eight-hour day of uninterrupted delivery and
  an estimate denominated in hours quietly pretends they do.
- Not weeks, because a week is a lumpy unit that hides a factor-of-five range.
- Not story points, because they do not survive contact with a client
  conversation, and every estimate we produce eventually has to be explained to
  somebody who is paying for it.

A developer-day is one competent person, on this task, for a normal working day,
including the meeting they will be dragged into and the code review they owe
somebody.

## The checklist

Run every estimate through these before writing a number down:

1. **Have we seen the actual system?** Not a description of it, not a diagram —
   the running system and its data. If not, the estimate is a guess wearing a
   suit, and the answer is a paid discovery, not a number.
2. **What is the worst thing we might find?** Name it explicitly. Bramwell & Foss
   taught us that "undocumented logic bolted on by a departed contractor" is not
   a tail risk in migration work; it is the base case.
3. **Who is the single point of failure?** If exactly one person on the team could
   do this work, say so in writing at estimate time, not at week six.
4. **What is the integration we are assuming is easy?** There is always one, and
   it is never easy. Klarna was the one nobody named.
5. **Is any of this genuinely novel to us?** Novel work gets scoped as
   time-and-materials. It does not get a fixed price with a bigger buffer bolted
   on — a buffer is for known-unknowns, and novel work is the other kind.

## Estimating a migration specifically

Migrations get a minimum of one week of paid technical discovery before any
estimate is issued at all. This is not negotiable and it is not a sales tactic;
it is the direct output of the Bramwell & Foss retrospective, where two days of
free discovery hid four unbilled days of untangling and five weeks of calendar
overrun.

The discovery week produces three artefacts: an inventory of every integration
and third-party app touching the system, a list of every piece of behaviour that
exists in code but not in documentation, and a written statement of what is
explicitly *out* of scope.

## Worked example

Northgate's second-phase depot rules change, estimated January 2026:

```text
Sam       Priya     agreed
  6.0       7.5       7.5   solver changes for the new ADR constraint
  3.0       3.0       3.0   admin UI for editing depot rules
  2.0       5.0        —    manifest import changes  <-- 150% apart, re-scoped
  1.5       2.0       2.0   tests and release
```

The manifest import line is the whole reason we estimate twice. Sam had assumed
the existing CSV import needed a new column; Priya had assumed Freightlink's
export format was changing and the whole import needed reworking. Neither was
right — a twenty-minute call with Priti established the format was stable — and
the re-estimated line came in at 2.0. Without the second estimate we would have
carried three phantom days into the quote and never known.

## What we do not do

We do not pad individual line items "to be safe". Padding at the line level is
invisible, uncontrolled and compounds silently across a large estimate. The
buffer is applied once, at the pricing stage, where it is explicit and everyone
can see it.
