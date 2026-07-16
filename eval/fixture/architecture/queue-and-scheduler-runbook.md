# Runbook: queue backlogs and missed schedules

## Scope

What to do when background work stops happening. Two mechanisms, two failure
shapes, two sets of steps. This runbook tells you how to get the work moving
again. It does not explain why the split exists or which mechanism a new job
should use — that is a design question, and ADR 002 answers it.

## Shape 1: the BullMQ queue is backing up

### Symptom

The tracking page shows an ETA that is visibly wrong or visibly not moving, and
the `eta:recompute` queue depth on the BullMQ dashboard is climbing rather than
oscillating around zero. The 2-second objective from webhook receipt to updated
ETA is blown, usually by minutes rather than seconds.

### Triage

```bash
# how deep is it, and is it moving?
redis-cli --scan --pattern 'bull:eta:recompute:*' | wc -l

# what's in the failed set? BullMQ keeps failures rather than dropping them
redis-cli llen bull:eta:recompute:failed
```

Three causes, in descending order of how often we have actually seen them:

1. **The worker pool is scaled to zero or crash-looping.** Check the ECS service
   first, always. Roughly two-thirds of "the queue is stuck" pages have turned
   out to be "nothing is consuming the queue", and it is the cheapest thing to
   rule out.
2. **A poison job.** One job that throws on every attempt, burns its retries,
   lands in the failed set, and — crucially — does not block anything behind it.
   BullMQ is not a single-file queue. If throughput has stopped entirely, a
   poison job is *not* your cause, however tempting it is.
3. **Redis itself is unhappy.** ElastiCache memory pressure, evictions climbing.
   Remember that the same cluster serves the application cache on a different
   logical database, so cache hit rate falling off a cliff at the same time is a
   strong tell that the problem is the cluster, not the queue.

### Draining safely

Do not `FLUSHDB`. It will take the application cache with it, on the same
cluster, in the same breath. Retry the failed set explicitly instead, and if a
job is genuinely unprocessable, remove it individually and open a ticket with the
payload attached rather than deleting it and moving on.

## Shape 2: a scheduled job did not fire

### Symptom

The nightly invoice run did not produce invoices, or the Monday driver compliance
digest did not go out. Nobody notices for hours, because a schedule that does not
fire produces no error — it produces silence.

### Triage

Scheduled work is EventBridge Scheduler, not BullMQ, so none of the Redis
commands above will tell you anything. Check EventBridge's own invocation metrics
first:

```bash
# did the schedule fire at all?
aws scheduler get-schedule --name nightly-invoice-run

# did the target Lambda get invoked, and did it succeed?
aws logs tail /aws/lambda/invoice-run-trigger --since 12h
```

The common failure is not EventBridge missing its clock — in two years it never
has. It is the target Lambda succeeding at enqueueing the work while the work
itself then fails downstream, which means EventBridge's own metrics look perfectly
green while no invoices exist. Always follow the chain past the scheduler to the
thing that actually does the work.

### Re-running

Both the invoice run and the compliance digest are safe to re-run: they are keyed
on the business date, and a second run for the same date is a no-op rather than a
duplicate. This is a property we designed for deliberately and it is worth
preserving in any new scheduled job — the first question in review for anything
new on a clock is "what happens if this runs twice?"

## Escalation

If the queue is drained, the workers are healthy and the ETAs are still wrong, the
problem is `recomputeEta()` itself and not the transport. Hand it to the dispatch
squad; there is nothing further in this runbook that will help you.
