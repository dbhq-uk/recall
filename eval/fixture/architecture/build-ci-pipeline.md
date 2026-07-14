# Build and CI pipeline

## Overview

Every change to core-api goes through the same GitHub Actions pipeline before it can reach production, whether it's a one-line copy fix or a schema migration. This note describes the pipeline stages, what's required to merge, and roughly how often we actually ship.

## Pipeline stages

The workflow runs four stages in order, failing fast so an engineer isn't left waiting twelve minutes to discover a lint error:

```yaml
# .github/workflows/ci.yml (excerpt)
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15         # same major version as production
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run lint          # stage 1: eslint, including boundary rules
      - run: npm run typecheck     # stage 2: tsc --noEmit
      - run: npm test              # stage 3: unit + integration tests
      - run: npm run build         # stage 4: production bundle
```

1. **Lint and typecheck** - ESLint (including the `eslint-plugin-boundaries` module rules from `adr-001-modular-monolith.md`) and `tsc --noEmit` run first, since they're the fastest way to reject an obviously broken change.
2. **Unit tests** - run against mocked dependencies, no network or database access.
3. **Integration tests** - run against a throwaway Postgres 15 service container, migrated from scratch with `dbmate up` at the start of the job so every run starts from an identical, empty schema.
4. **Build and package** - a production Docker image is built and pushed to Amazon ECR, tagged with the short commit SHA.

## The fifth stage: migrations

There is a fifth job, `migrations`, which does not appear in the excerpt above because it only runs on pull requests that touch `db/migrations/`. It is, by a wide margin, the stage engineers see go red most often, and the code it reports when it does is `ERR_MIGRATION_NO_DOWN`.

This note deliberately does not reproduce what that code means or what a reviewer is supposed to do about it. That belongs to the migration policy, which is the single source of truth for the rule being enforced here, and copying the rule into two places is how the two places end up disagreeing. All this pipeline note claims is: if you see `ERR_MIGRATION_NO_DOWN` in a CI log, it came from the `migrations` job, and the migration policy is the document to open next.

## Configuration in CI

CI holds no production credentials at all. The integration-test job runs against a throwaway Postgres container and a stubbed identity provider, so `COGNITO_USER_POOL_ID`, `WAYFREIGHT_SERVICE_JWT_SECRET` and the rest are set to obviously-fake values in the workflow file rather than pulled from Parameter Store:

```yaml
# .github/workflows/ci.yml (excerpt, env block)
env:
  COGNITO_USER_POOL_ID: eu-west-2_TESTPOOL0   # stub; the real pools are per-environment
  WAYFREIGHT_SERVICE_JWT_SECRET: ci-not-a-real-secret
  MAX_RETRY_BUDGET_MS: 5000                   # shorter than prod so CI fails fast
```

If a test needs a real value from any of these to pass, that test is testing the wrong thing.

## Deployment

A successful build on `main` triggers AWS CodeDeploy to perform a blue/green deployment onto the ECS Fargate service described in `adr-001-modular-monolith.md`: CodeDeploy shifts traffic to the new task set gradually while watching the ALB's target group health checks, and automatically rolls back to the previous task set if error rates spike during the shift, without needing a human to notice and intervene.

## Branch protection

`main` cannot be pushed to directly. Merging requires: the four CI stages above passing, at least one approving review, and the branch being up to date with `main` at merge time (no merging a PR that hasn't seen the latest commits, which has caused subtle integration test gaps in the past when two migrations were written against the same "next" timestamp independently).

## Performance budget

The full pipeline, lint through image push, is budgeted at under 8 minutes; a run that exceeds it is treated as a regression worth investigating, not just a slow day.

## Deployment cadence

Across a typical week, `main` deploys to production roughly 14 times - small, frequent changes are the norm rather than infrequent batched releases, which keeps each individual deploy's blast radius small enough that the CodeDeploy automatic rollback described above rarely needs to trigger in the first place.
