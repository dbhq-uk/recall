# Breakdown notes

## Alternator failure, M6 near Tebay, June 2024

Battery warning light came on the dash while doing a steady 65mph northbound on the M6, just south of Tebay services, on a Friday evening heading up for a weekend in the Lakes rather than any of the logged trips. Dash also showed a brief "Check vehicle systems" message before the battery symbol settled in and stayed lit. Pulled into Tebay services rather than pushing on, since a dying alternator with no charge going back into the battery is the kind of fault that gets worse quickly, especially with headlights and the leisure electrics both drawing off the same starter battery for the DC-DC charger's input side.

Called the AA from the services car park. Recovery arrived in just under an hour, confirmed with a multimeter across the battery terminals that alternator output was reading barely above resting battery voltage with the engine running — should have been comfortably in the 13.8–14.4V range and wasn't. Diagnosed as a failed alternator rather than a wiring fault, since the drive belt was intact and tensioned correctly. Recovered to a garage in Kendal recommended by the AA driver, stayed there overnight in a nearby B&B rather than risk the drive home.

Replacement was a genuine Bosch alternator, garage fitted the next morning, total bill £410 including labour and the overnight recovery excess. Garage mentioned the original alternator's bearings were likely original to the van at 89,000 miles and had probably been on their way out for a while — no dramatic single cause, just old age. Lesson taken from this: now carry a basic multimeter in the tool roll, since being able to at least confirm charging voltage at the roadside would have saved some uncertainty while waiting for recovery.

## Glow plug fault, February 2024

Amber engine warning light appeared one cold morning on the drive to work, van also noticeably harder to start than usual and running rough for the first minute or so. Read the fault with a cheap ELM327 Bluetooth OBD reader plugged into the dash port and an app on the phone — came back with code P0671, cylinder 1 glow plug circuit malfunction. Given the cold-start symptoms this matched exactly what you'd expect: one dead glow plug meaning that cylinder wasn't getting the extra heat it needed on a cold morning.

Rather than replace just the one, had the full set of four replaced at the same time at a local independent garage — false economy to pay the labour cost of getting to the plugs twice when the others were the same age and likely to follow soon after. £180 all in for parts and labour. Cold starts back to normal immediately, no repeat of the code since.

## Limp mode on the A1(M), October 2025

Van dropped into limp mode — power gone, engine light on, wouldn't rev past about 2,500rpm — northbound near Wetherby on the way to a family thing in Northumberland. The DPF light was also lit on the dash, which sent me straight down the wrong path for about an hour, because the obvious assumption when a diesel goes into limp mode with a DPF warning showing is that the filter has finally blocked itself solid.

It hadn't. Pulled over, plugged in the OBD reader expecting a soot-loading code, and got P0234 — turbocharger overboost — with no DPF code stored at all. The DPF light on this van's dash apparently comes on for a general "engine management fault" as well as for an actual filter problem, which is either a design decision or a quirk of this model year, and either way is genuinely misleading. Nothing wrong with the DPF whatsoever.

Actual cause, once the garage in Boroughbridge had it on the ramp the next morning: a split boost hose between the intercooler and the inlet manifold. The rubber had perished at the crimp and was blowing off under load, which the ECU read as an overboost fault and responded to by pulling the van into limp mode to protect itself. £95 for a new hose and half an hour of labour.

Lesson, and it's the useful one: read the code before believing the dash. A warning light is a summary and this van's summary is lossy. Half an hour with a £12 reader would have told me the DPF was fine before I'd finished convincing myself it wasn't.

## Puncture repair kit use

Picked up a nail in the nearside rear tyre on the A61 north of Sheffield, November 2023. No spare wheel fitted as standard on this van, just a repair kit and a 12V compressor in the boot cubby. Plugged the puncture with the kit at the roadside — straightforward with the nail still in place to mark the hole — reinflated with the compressor and drove on. Had it properly inspected and a permanent internal patch fitted at a tyre garage within a couple of days as recommended, since a plug alone is only meant to be a temporary fix. Tyre's held perfectly since.
