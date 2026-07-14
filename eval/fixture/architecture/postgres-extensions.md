# Postgres Extensions

## Overview

Wayfreight's primary datastore is a single Amazon RDS for PostgreSQL 15.4 instance, `wayfreight-core-prod`, shared by the core-api service, the reporting read replica and the nightly batch jobs. Rather than reaching for bespoke external services for scheduled SQL jobs, geofencing or embedding similarity search, we lean on Postgres extensions wherever the feature fits. This note is the reference for which extensions are enabled on that instance, why each one earned its place, and how to add a new one without causing an outage.

## Extension inventory

### pgvector (0.5.1)

Adds a vector data type and approximate nearest-neighbour indexing to Postgres, and backs the incident report similarity search described in `adr-004-vector-store.md` (see that document for the schema and query shape). pgvector ships as a pure SQL-visible extension with no background worker, so it needs no changes to `shared_preload_libraries` - a plain `CREATE EXTENSION` is sufficient.

### pg_cron (1.6)

Runs in-database maintenance jobs that don't warrant a full application worker: a nightly `REFRESH MATERIALIZED VIEW CONCURRENTLY depot_utilisation_daily`, a weekly `VACUUM ANALYZE` of the three largest tables, and monthly partition creation for `tracking_events`. Jobs are registered in the `cron.job` table and executed inside the database process itself, which is precisely why it needs to be preloaded (see below). We cap concurrency with `pg_cron.max_running_jobs = 4` so maintenance work can never starve foreground query capacity during business hours.

### pg_stat_statements

Tracks normalised query text, call counts and timing statistics for every statement executed on the instance. The "Slow Queries" panel on our Grafana database dashboard reads this view directly from the read replica. Like pg_cron, it hooks into the query executor at process start-up and must therefore be preloaded rather than merely created.

### postgis (3.4)

Used for depot catchment-area polygons and the `ST_Contains` checks that decide whether a delivery address falls inside a driver's assigned zone. It registers a large number of geometry types and functions but runs no background worker, so no preloading is required.

### pgcrypto

Provides `pgp_sym_encrypt` and `pgp_sym_decrypt`, used to encrypt driver bank account fields at rest with a symmetric key held outside the database, in AWS Secrets Manager. No preloading required.

## Installing an extension safely

### CREATE EXTENSION is not always enough

Most of the extensions above only need to be registered once inside a given database:

```sql
-- run once per database, not once per cluster
CREATE EXTENSION IF NOT EXISTS pgvector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

A smaller set of extensions - pg_cron and pg_stat_statements among them - install a background worker or hook into query execution before any client connection is even accepted. Those must be named in `shared_preload_libraries`, a parameter that Postgres reads exactly once, at postmaster start-up. The shared memory and background worker slots those extensions need are allocated while the server is still booting, so adding a library to `shared_preload_libraries` always requires a full instance restart. A configuration reload is not sufficient, and if you skip the restart the extension's `CREATE EXTENSION` statement will simply fail rather than degrading gracefully.

On a self-managed box this means editing `postgresql.conf` directly:

```bash
# postgresql.conf
shared_preload_libraries = 'pg_cron,pg_stat_statements'
pg_cron.max_running_jobs = 4
```

and then restarting the service:

```bash
sudo systemctl restart postgresql
```

### Enabling extensions on Amazon RDS

RDS doesn't expose `postgresql.conf` directly, so the same change is made in two steps:

1. Add `pg_cron,pg_stat_statements` to the `shared_preload_libraries` parameter on the instance's DB parameter group, `wayfreight-pg15-params`. RDS also restricts which extensions may be created at all, via an allow-list parameter called `rds.allowed_extensions`; anything not on that list raises `ERROR: extension "x" is not allow-listed for "rds_superuser" users` when you try `CREATE EXTENSION`.
2. Apply the parameter group change and reboot the instance - RDS refuses to apply a "static" parameter such as `shared_preload_libraries` without one:

```bash
# apply the change and force the restart in one step
aws rds modify-db-instance \
  --db-instance-identifier wayfreight-core-prod \
  --apply-immediately \
  --db-parameter-group-name wayfreight-pg15-params
```

3. Once the instance reports `available` again, run the `CREATE EXTENSION` statements from above.

## Version pinning

Extension versions are pinned in `migrations/extensions.lock` and bumped one minor version at a time during the Tuesday maintenance window, never as part of a feature deploy.
