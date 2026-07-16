---
title: Electrical system - T6 conversion
tags: [van, electrics, solar, battery]
---

# Electrics

## System overview

Simple 12V leisure circuit, charged from two sources (engine via DC-DC, and solar), running lighting, USB sockets, the water pump, the roof fan and a compressor fridge. Deliberately kept off-grid capable — no shore power hookup fitted, since most nights are spent wild camping rather than on serviced pitches.

## Leisure battery

100Ah Renogy deep-cycle AGM, model RBT100AGM12-G1, mounted in a ventilated box under the passenger seat riser. Went AGM rather than lithium mainly on cost, but also because AGM doesn't need a low-temperature charge cutoff — didn't want to deal with a lithium BMS refusing to charge below 0°C on a winter morning in the Cairngorms. Trade-off is usable capacity: only really draw it down to 50% (so ~50Ah usable) to keep cycle life reasonable, versus the much deeper discharge you'd get away with on lithium.

## Charging

### Engine charging (DC-DC)

Renogy 40A DC-DC charger, model RBC40D1S, fed from the starter battery via 6mm² cable. ANL fuses rated 40A at both the starter battery end and the leisure battery end. The DC-DC unit also handles the transition to solar input automatically when the engine isn't running, so it's doing double duty as the charge controller's backup path.

### Solar

200W monocrystalline panel (Renogy) feeding a Victron SmartSolar MPPT 100/20 charge controller, mounted on the wall behind the passenger seat where it's easy to read the Bluetooth-paired display. Cabling is 4mm² solar cable with MC4 connectors running through a single roof gland — the only roof penetration on the whole van, and it is bedded and capped with Sikaflex, same as everything else that goes through that roof. The panel's own brackets are bonded rather than bolted; the roof conversion notes cover why, and this note is only concerned with what comes down the cable from them. On a clear day in summer this alone comfortably covers the fridge and lighting load without touching engine charging at all.

## Distribution

Blue Sea Systems ST-Blade 12-way fuse block for everything downstream of the leisure battery. Circuit fuse ratings, for reference:

- USB charger sockets (x2): 5A
- Water pump: 7.5A
- Fridge: 10A
- Interior lighting (LED strip, two zones): 3A each
- Roof fan: 15A
- Spare circuit (unused, capped): 10A

## Fridge

Dometic CFX3 35 compressor fridge, quoted 45W draw when the compressor is actually running, but duty cycle sits around 30–35% in normal use so average draw is much lower — roughly 15W continuous once temperature is stable. Runs off the leisure circuit permanently, no separate isolation switch, since the battery monitor low-voltage cutoff protects it anyway.

## Inverter

500W pure sine wave inverter (Renogy), wired directly to the leisure battery with its own 60A fuse close to the battery terminal. Used only for laptop charging — deliberately didn't size it for a kettle or anything else power-hungry, since that load would be better served by gas.

## Battery monitoring

Victron BMV-712 shunt-based monitor on the negative busbar, reporting state of charge over Bluetooth. Low voltage alarm set at 11.8V, with a relay-triggered load cutoff at 11.5V wired in series with the fuse block feed — stops the fridge and lighting from flattening the battery below a safe point overnight.

## Power budget

Wrote a quick script to sanity-check the daily amp-hour budget before deciding on the 200W panel size:

```bash
#!/usr/bin/env bash
# rough daily amp-hour budget for the leisure circuit
# figures in watt-hours per day, battery nominal 12V

fridge_wh=360      # ~15W average x 24h
lighting_wh=40      # couple of hours a night, LED
usb_wh=30           # phones, headtorch batteries
fan_wh=15           # occasional low-speed running

total_wh=$(( fridge_wh + lighting_wh + usb_wh + fan_wh ))
total_ah=$(echo "scale=1; $total_wh / 12" | bc)

# expect roughly 4h of useful solar in the UK shoulder season
echo "Daily load: ${total_wh}Wh (~${total_ah}Ah at 12V)"
```

Came out around 37Ah/day in typical use, well within what the 100Ah AGM and 200W panel combination can sustain through a few overcast days.
