# Northgate Freight Solutions — Retainer Engagement

Northgate Freight Solutions run a fleet of curtain-sider lorries out of a yard near Avonmouth. In 2024 they asked us to replace a spreadsheet-and-whiteboard scheduling process with proper software: a system matching drivers, vehicles and job slots against a daily delivery manifest.

## Overview

### How the relationship started

Northgate's ops manager had seen a driver double-booked twice in one month — once because the whiteboard got wiped before the change was written down anywhere else — and decided that was the last straw. We were introduced through an existing client's accountant, did a half-day free discovery call, and were commissioned within three weeks.

### Commercial terms

Retainer signed 3 October 2024: £8,500 per month for a guaranteed three-days-per-week allocation, initial twelve-month term. Renewed 4 March 2026 for a further twelve months at the same day rate; no change to scope, no change to the three-day allocation.

Our contact throughout has been Priti Anand, Head of Operations, who reports directly to the MD and has been decisive about priorities in a way that makes this one of our easier retainers to run — she'll tell us "no" to a nice-to-have rather than let scope drift, which is rarer than it should be.

## The system

### Scheduling engine

The core of the system is a constraint solver that assigns jobs to driver-vehicle pairs against a rolling seven-day window, respecting drivers' hours rules, vehicle MOT and tachograph calibration dates, and customer delivery windows. We built the solver ourselves rather than reaching for an off-the-shelf routing package, because Northgate's constraints (some customers only accept deliveries in a two-hour slot; some drivers are only certified for ADR loads) didn't map cleanly onto anything we evaluated, and the customisation cost of the packaged options would have eaten most of a year's retainer anyway.

### Manifest import

Each night at 02:00 the system pulls the next day's manifest from Northgate's transport management system (a third-party product called Freightlink, which they'd already been using for years and had no appetite to replace) via a CSV export dropped into an SFTP folder. This has been more reliable than the API integration we originally tried, which Freightlink's own support team eventually admitted was undocumented and barely maintained.

### Who works on it

Sam leads, Priya covers the solver, and Tom Vickers (through his own company, Vickers Dev Ltd) has been on the retainer since 2022, currently around two days a week of the three-day allocation. Tom knows the Freightlink import better than anyone here does, largely because he wrote most of it and then spent an unhappy fortnight discovering what Freightlink's support team eventually admitted about their own API.

Tom also bills days against a second, entirely separate client engagement. The two are contracted and paid on different bases, and the reasons for that are not a Northgate matter at all — they are set out in the IR35 notes, which is the only place that determination is recorded and the only place anyone should be reading it from. Nothing about how Tom is engaged here should be inferred from how he is engaged elsewhere, or the reverse.

### Uptime and support

SLA: 99.5% uptime during Northgate's operating hours (05:00–20:00 Monday to Saturday), measured monthly. We miss this in roughly one month in six, almost always because of a scheduled AWS maintenance window that lands badly, not because of application bugs. Support is business-hours only under the retainer; anything outside that is chargeable at the senior day rate, pro-rated.

## Monitoring config

```yaml
# uptime-monitor.yml — Northgate scheduling system checks
# Polled by our internal Grafana Cloud account every 60s
checks:
  - name: scheduling-api-healthcheck
    url: https://schedule.northgatefreight.example/api/health
    interval: 60s
    # Alert if three consecutive checks fail
    failure_threshold: 3
    notify:
      - pagerduty:kestrel-oncall
  - name: manifest-import-job
    # Runs nightly at 02:00, imports the next day's manifest from Freightlink
    schedule: "0 2 * * *"
    timeout: 15m
    notify:
      - slack:kestrel-alerts
```

## Lessons

The retainer model works well here because Northgate's needs are genuinely ongoing — new customer onboarding, new depot rules, driver certification changes — rather than a project pretending to be a retainer because nobody wants to write a proper change-request process. We've suggested this structure to two other clients since and it's only been right for one of them.

One thing we'd flag to future-us: the three-day allocation only works because Priti batches her requests into a weekly priorities call rather than pinging ad hoc through the week. When we tried the same retainer shape with a less organised client early on, the constant context-switching cost us close to a day a week in overhead that never got billed. Retainers need a client who can do their half of the discipline too.
