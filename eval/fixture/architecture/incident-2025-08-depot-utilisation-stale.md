# Incident postmortem: stale depot utilisation view, 14 August 2025

**Severity:** SEV-3 (internal reporting only; no customer impact)
**Duration:** roughly 61 hours before detection
**Author:** R. Okafor

## Summary

The `depot_utilisation_daily` materialised view served two-day-old numbers to the
operations dashboard from the morning of 12 August until 21:00 on 14 August.
Nobody noticed for two and a half days because the dashboard renders happily from
a stale view — it has no freshness indicator — and the numbers were plausible.
Two depot managers made staffing calls on the stale figures. Neither call turned
out badly, which is luck rather than process.

## What happened

The nightly refresh is a pg_cron job, registered in `cron.job` as
`refresh-depot-utilisation`, firing at 02:30 UTC. On the night of 11–12 August it
overlapped with an unusually long ad-hoc `REINDEX` that an engineer had started
manually at 01:50 and had not announced anywhere.

`pg_cron.max_running_jobs` is set to 4, which correctly stopped the queue of
scheduled work from piling up unboundedly, but the refresh job itself sat blocked
behind the reindex, exceeded its statement timeout, and was recorded in
`cron.job_run_details` with status `failed`. pg_cron then did exactly what it is
configured to do: nothing. It does not retry a failed job, and it does not alert.
The next night's run failed the same way for a different reason (the view was by
then locked by the previous night's half-rolled-back attempt), and after that the
job simply kept failing silently.

## Why detection took 61 hours

Three separate gaps, none of which is pg_cron's fault:

1. **`cron.job_run_details` was not being monitored at all.** We had a dashboard
   panel for slow queries fed by `pg_stat_statements`, and nothing whatsoever
   watching whether scheduled jobs had actually run. A job that fails quietly is
   indistinguishable from a job that succeeded.
2. **The dashboard has no freshness stamp.** Adding `last_refreshed_at` to the
   view and surfacing it in the panel header is a fifteen-minute change that
   would have caught this on the first morning.
3. **Ad-hoc maintenance was not announced.** The engineer who started the reindex
   did so outside the Tuesday window, without a message in `#eng-oncall`. This is
   not a hanging offence, but it removed the one human who could have connected
   cause to effect.

## Actions

| Action | Owner | Status |
| --- | --- | --- |
| Alert on any `cron.job_run_details` row with status `failed` in the last 24h | S. Lindqvist | Done, 19 Aug |
| Add `last_refreshed_at` to `depot_utilisation_daily` and render it in the panel | R. Okafor | Done, 22 Aug |
| Ad-hoc maintenance on the primary must be announced in `#eng-oncall` first | Team norm | Agreed |
| Consider moving the refresh out of pg_cron entirely | — | Rejected, see below |

## The action we did not take

There was an argument in the review for moving the refresh out of pg_cron and
onto EventBridge Scheduler, on the grounds that EventBridge would at least have
retried and alerted. We rejected it. The failure here was not "pg_cron is the
wrong tool for an in-database maintenance job" — it plainly is the right tool for
a `REFRESH MATERIALIZED VIEW`, which wants to run inside the database rather than
be triggered from outside it. The failure was that we ran a job with no monitoring
on whether it ran. Moving the job somewhere else would have papered over that and
left every *other* unmonitored pg_cron job exactly as exposed. We fixed the
monitoring instead.
