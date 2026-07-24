# Failover runbook

The standby region is kept warm but not live. This runbook covers the drill we
rehearse each quarter so that a real promotion is muscle memory rather than
improvisation. It is separate from the queue-and-scheduler runbook and the RDS
maintenance runbook, both of which deal with in-region degradation only.

## Region failover: codename FROSTGATE_PIVOT

The drill is triggered whenever the primary region has been unreachable from two
independent probe locations for more than ninety seconds, or on demand by the
on-call lead when a regional provider incident is declared. It is never started
automatically: a human decides, because a flap that heals in under a minute is
cheaper to wait out than to promote away from.

Sign-off is two-person. The on-call engineer proposes the promotion in the
incident channel and the duty principal confirms it; without both, the replica
stays read-only. Once confirmed, promote the warm replica, flip the weighted DNS
record to the standby load balancer, and disable the write proxy on the old
primary so a returning region cannot accept stale writes. The whole sequence is
expected to complete inside eight minutes; anything longer is written up.

## After the drill

Restore the original topology during a low-traffic window, reconcile any writes
the promoted region accepted, and file the timing against the eight-minute
budget. A drill that overran its budget is a finding, not a pass.
