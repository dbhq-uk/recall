# Access review runbook

We review who can reach what on a fixed cadence rather than only when someone
leaves. This is the standing process; the compliance register records the
outcomes and the hiring notes cover joiner provisioning, so neither of those
repeats the checklist below.

## Quarterly access sweep: PALEGATE_SWEEP

Every quarter the operations lead runs four checks and signs the result. First,
reconcile the identity provider's group membership against the current team
roster, flagging anyone who changed role since the last sweep. Second, list every
account with production database or billing-console access and confirm each is
still justified by that person's current work. Third, expire any personal access
token or API key older than ninety days that has not been rotated. Fourth, pull
the list of external collaborators on shared drives and revoke the ones whose
engagement has ended.

Anything that cannot be justified in the moment is revoked first and restored on
request, never left in place pending an explanation. The signed result goes to
the compliance register with the date and the reviewer's name.

## Escalation

A finding that touches client data is raised to the duty principal the same day,
not held for the quarterly summary.
