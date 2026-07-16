---
title: NC500 trip log
tags: [trip, scotland, nc500, wild-camping]
dates: 2023-09-14 to 2023-09-28
---

# NC500, September 2023

## Route summary

Anticlockwise from Inverness, up the east coast to John o' Groats, along the north coast through Durness, then down the west coast through Ullapool and Applecross before cutting back to Inverness via Loch Carron. Two weeks, no fixed itinerary beyond roughly which coast we'd be on each few days — the whole point was not booking campsites in advance and seeing how far the fuel and the weather took us each day.

### Standout wild camping spots

- Layby above the coast road just north of Bettyhill, grass verge big enough for one van, sea view straight out the back doors, no facilities.
- Small gravel pull-in on the approach to Applecross over the Bealach na Bà pass — arrived late afternoon after the climb, stunning at sunset, but very exposed to wind; the van rocked noticeably overnight.
- Car park at the far end of Sandwood Bay access track (the walk-in car park, not the beach itself) — quiet, a couple of other vans, respectful about spacing out rather than clustering.
- Forestry Commission car park a few miles south of Durness, tucked into trees, sheltered from the coastal wind that had made the previous two nights hard to sleep through.

## Weather log

First week was unseasonably good — high pressure sat over the north coast for about five days running, several genuinely warm afternoons around Durness. Turned properly wet and windy for the Applecross crossing in the second week, driving rain on the pass itself with visibility down to maybe 50 metres near the top. Bealach na Bà is not a road to do in bad weather in a tall van if it can be avoided; the crosswind on the exposed hairpins was the most unsettled the van has felt to drive, roof conversion notwithstanding.

## Fuel cost tally

Kept a running note of every fill-up to see what the trip actually cost in diesel, then wrote a quick script afterwards to total it up:

```python
#!/usr/bin/env python3
# nc500 fuel log - litres and price per litre from each fill-up receipt

fills = [
    (52.1, 1.549),  # Inverness, day 1
    (48.7, 1.639),  # Wick, day 4
    (55.3, 1.719),  # Durness, day 7 - most expensive of the trip, remote pump
    (49.9, 1.599),  # Ullapool, day 10
    (44.2, 1.579),  # Fort William, day 13, on the way home
]

total_litres = sum(l for l, _ in fills)
total_cost = sum(l * p for l, p in fills)

print(f"Total litres: {total_litres:.1f}")
print(f"Total spent: £{total_cost:.2f}")
print(f"Average price/litre: £{total_cost / total_litres:.3f}")
```

Came out at just over £395 in diesel for the fortnight, average price per litre noticeably higher than home once north and west of Inverness — the Durness fill-up alone was nearly 17p/litre more than the first tank.

## Daily log — Bealach na Bà day

Worth writing this one up properly since it was the hardest driving day of the trip. Left the Sandwood car park early, long transit day down through Kinlochbervie and Scourie before turning inland for the approach to Applecross. The pass itself starts innocuously enough — a fairly ordinary single-track road climbing gently through a glen — before the gradient signs start appearing, first 1-in-6, then a genuine 1-in-5 section with a set of hairpins stacked almost on top of each other near the summit.

Weather turned properly bad about two-thirds of the way up: driving rain, low cloud rolling across the road in patches thick enough to lose sight of the verge markers for a few seconds at a time. Dropped to second gear for the steepest hairpins and kept speed right down, mindful of the raised roof's extra side area catching the crosswind on the exposed bends. Met one campervan coming the other way on a hairpin with genuinely no passing space — had to reverse back around the bend to a slightly wider pull-in, not something I'd want to repeat in those conditions.

Summit car park was a relief, though visibility was down to maybe 50 metres and there wasn't much point stopping to admire what would apparently, on a clear day, be one of the best views on the whole route. Descent into Applecross was gentler than the climb but the road surface was running with water in several places. Found the exposed gravel pull-in mentioned above for the night, more out of necessity than choice given how late it was by the time we were down — wind carried on into the small hours and neither of us slept brilliantly, but the alternative of pushing on further in the dark on unfamiliar single-track roads seemed worse. Would do the pass again but would check the forecast more carefully first and build in a weather contingency day either side.
