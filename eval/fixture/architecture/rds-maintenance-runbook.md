# Runbook: the Tuesday maintenance window

## Scope

This is the operational checklist for the weekly maintenance window on
`wayfreight-core-prod`, 02:00–04:00 UTC every Tuesday. It covers what we do
during the window and in what order. It does **not** cover which extensions are
installed on the instance or why — the extensions reference note is the source of
truth for that, and this runbook assumes the inventory is already correct and
unchanged.

On-call owns the window. If you are on call and have not run one before, pair
with someone who has; the steps are short but the ordering matters.

## Before the window

### T-24h: freeze the parameter group

`wayfreight-pg15-params` is frozen from 02:00 Monday. Nobody edits it during the
freeze, and in particular nobody touches `shared_preload_libraries` during a
maintenance window — a parameter-group edit landing mid-window is the single
easiest way to turn a routine two-hour window into an incident, because the
reboot semantics interact badly with whatever else you were halfway through. If
you need to change the extension set, that is its own separately-planned change
with its own comms, not something bolted onto a Tuesday.

### T-1h: quiesce the scheduled jobs

pg_cron will happily kick off a nightly `REFRESH MATERIALIZED VIEW CONCURRENTLY`
in the middle of a `REINDEX`, and the two will contend for exactly the resources
you are trying to free up. Pause the jobs rather than hoping the timing misses:

```sql
-- pause every pg_cron job before the window opens
UPDATE cron.job SET active = false;

-- confirm nothing is still running
SELECT jobid, jobname, status, start_time
FROM cron.job_run_details
WHERE status = 'running';
```

Note that `pg_cron.max_running_jobs = 4` bounds concurrency but does not stop a
job that has *already* started, so check `job_run_details` rather than trusting
the cap.

## During the window

1. Confirm the replica lag on the reporting replica is under 5 seconds. If it is
   not, stop and escalate; do not proceed into a `REINDEX` with a replica already
   struggling to keep up.
2. Run the HNSW `REINDEX` for the incident-report vector index. This is the
   longest step, typically 35–50 minutes at current row counts, and it is why the
   window is two hours rather than one.
3. Run `VACUUM ANALYZE` on the three largest tables if pg_cron's weekly job did
   not complete cleanly in the preceding week.
4. Apply any pending minor-version engine upgrade. RDS reboots the instance to do
   this; expect roughly 90 seconds of connection errors and let the ALB health
   checks drain and restore naturally rather than intervening.

## After the window

Re-enable the scheduled jobs and confirm they pick up on their next natural fire
time rather than immediately backfilling every missed run:

```sql
UPDATE cron.job SET active = true;
SELECT jobid, jobname, schedule, active FROM cron.job ORDER BY jobid;
```

Then check `pg_stat_statements` has repopulated — it resets on restart, so an
empty slow-query panel for the first hour after a reboot is expected and is not
an incident, however many times somebody raises it as one.

## Comms

Post in `#eng-oncall` when the window opens and when it closes, and note in the
close message whether the engine was rebooted, because a reboot invalidates the
"nothing changed" assumption for anyone debugging something odd the next morning.
Post-window questions about extension behaviour go to the extensions note, not to
whoever happened to be holding the pager.
