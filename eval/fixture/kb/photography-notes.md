---
title: Photography Notes
tags: [photography, camera, lenses, settings]
---

# Photography Notes

Settings, lens notes and a few workflow bits for the Fujifilm kit. Mostly landscape and some portrait work, plus an ongoing attempt at astrophotography that's had mixed results.

## Camera

Fujifilm X-T4, APS-C sensor, in-body stabilisation which has been genuinely useful for handheld shots down to surprisingly slow shutter speeds. Battery is the NP-W126S — always carry two spares on a full day out, since the IBIS and EVF between them chew through a charge faster than the older X-T2 ever did.

## Lenses

### Fujinon XF 35mm f/1.4 R

The lens that stays on the camera by default. Equivalent to roughly 53mm on full frame, so a natural "normal" field of view. Autofocus is noticeably slower and noisier than the newer f/2 version, a known trait of this older optical design, but the rendering and out-of-focus character at f/1.4 is worth the trade-off for portrait work.

### Fujinon XF 90mm f/2 R LM WR

Bought for a wedding I was asked to shoot informally in 2023. Equivalent to roughly 137mm, properly sharp wide open, and the weather resistance (the WR in the name) has been tested more than once in unplanned drizzle without any issue. Heavier than expected the first time picking it up after the 35mm.

### Fujinon XF 16-55mm f/2.8 R LM WR

The all-rounder for days when carrying multiple primes isn't practical — walking around a city, mostly. Constant f/2.8 aperture through the zoom range, no image stabilisation built into the lens itself (relies entirely on the body's IBIS), which is a deliberate trade Fuji made to keep the optical design simpler.

## Astrophotography

### The 500 rule

For a rough guide to the maximum shutter speed before star trails become visible on an APS-C sensor, divide 500 by the focal length and then further divide by the crop factor (1.5 for Fuji's sensor). For the 16-55mm at its widest (16mm), that works out to roughly 500 / 16 / 1.5 ≈ 20 seconds as a starting point, though in practice anything past about 15 seconds at that focal length starts showing slight trailing on close inspection at 100%.

### Typical settings

For a reasonably dark sky (rural, minimal light pollution), starting point is:

```text
# astro settings - starting point
aperture     f/2.8 (widest available on the 16-55mm)
shutter      15s
ISO          3200
focus        manual, infinity, checked via live view zoom on a bright star
white balance  ~3800K, adjusted in raw processing afterwards
```

#### Noise and ISO trade-off

ISO 3200 is noisier than I'd like on the X-T4's APS-C sensor, but pushing it lower means either a longer shutter (star trailing) or a wider aperture (already maxed at f/2.8 on this lens), so it's the compromise that gives the least-bad result overall. Noise reduction in post via Capture One's luminance slider cleans up a fair amount without smearing detail too badly, provided it isn't pushed past about 40 on the slider.

## Long exposure landscape

### ND filters

Lee Filters "Big Stopper", a 10-stop screw-in ND, used for smoothing water and cloud movement in daylight long exposures. At base ISO and a moderate aperture (f/8-f/11), the Big Stopper turns what would be a 1/60s exposure into roughly 15-17 seconds — enough to blur moving water into that smooth, misty look without needing to wait for dusk. Composing and focusing has to happen before screwing the filter on, since almost no light gets through it once it's fitted; the viewfinder and even live view go essentially black.

## Portrait sessions

Settings vary a lot by light, but the recurring starting point outdoors in overcast conditions (soft, even light, minimal harsh shadow) is f/2 on the 90mm, 1/250s, auto ISO capped at 3200. Overcast days are consistently the easiest conditions to shoot portraits in — direct sun forces either heavy shadow under the eyes or a reflector/fill flash setup that adds complexity most casual sessions don't need.

## Editing workflow

Capture One rather than Lightroom, mainly for the colour grading tools and the fact it handles Fuji's X-Trans sensor raw files (compressed RAF) noticeably better for fine detail than Lightroom did the last time a direct comparison was tried, back in 2022. Styles saved per shoot type (a "landscape" base adjustment, a separate "portrait" base) applied on import, then tweaked per image from there rather than starting from scratch every time.
