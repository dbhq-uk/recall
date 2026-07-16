# OBD-II codes — cheat sheet

Codes I have actually pulled off this van with the ELM327 reader, plus the ones I
keep half-remembering and looking up again. This is a lookup table, nothing more:
it says what a code means, not what was done about it. Where a code has actually
appeared on this van there is a pointer to the notes that tell the story.

Van is the 2016 T6, 2.0 TDI, engine code CXHA.

## Codes seen on this van

| Code | Meaning | When | Notes |
| --- | --- | --- | --- |
| P0671 | Glow plug circuit, cylinder 1 — malfunction | Feb 2024 | See the breakdown notes for the diagnosis and what was done |
| P2002 | Diesel particulate filter efficiency below threshold, bank 1 | Autumn 2022 | Appeared alongside the DPF dash light. See the service log |
| P0401 | EGR flow insufficient | Never on this van | Listed because it is the code people confuse with a DPF fault |
| P2463 | DPF — soot accumulation | Never | The one you get if you ignore P2002 for long enough |

## The glow plug family

`P0671` through `P0674` are the same fault on cylinders 1 to 4 respectively. A
single one of them is a single dead plug. Two or more at once, or a code that
comes straight back after a plug change, points at the glow plug control module
rather than the plugs themselves, which is a considerably more expensive
conversation.

Symptom pattern for a single dead plug: hard cold start, rough running for the
first thirty to sixty seconds, then completely normal once the engine is warm.
Perfectly driveable, and easy to ignore for weeks, which is what most people do.

## The DPF family

The DPF codes are the ones worth understanding properly, because the light on the
dash does not distinguish between them and the reader will:

- **P2002** — the filter is not doing its job well enough. Usually soot loading.
- **P2463** — soot accumulation past the point where a normal regeneration cycle
  will clear it. This is the "get it to a garage" one.
- **P244A / P244B** — differential pressure across the filter is out of range,
  which as often as not means the pressure *sensor* has failed rather than the
  filter, and replacing a filter on the strength of this code without checking the
  sensor is an expensive mistake.

The service log covers what has actually happened with the DPF on this van and how
it was dealt with. This page is only here so that next time the light comes on I
read the code before I panic, rather than after.

## Clearing codes

The reader will clear a code. Clearing a code does not fix anything, and clearing
one before a garage sees it just means paying somebody to reproduce a fault you
had already reproduced yourself. Write the code down, then clear it if you must,
and if it comes straight back, stop clearing it.

## Kit

Cheap ELM327 Bluetooth dongle in the glovebox, paired with Car Scanner on the
phone. Cost about £12. It has paid for itself several times over purely by
turning "warning light, unknown cause, book it in somewhere" into "warning light,
known cause, decide whether it can wait".
