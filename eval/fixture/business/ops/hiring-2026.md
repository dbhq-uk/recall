# Hiring Notes — 2026

## Headcount context

We're five people as of March 2026: Alex Petrova (director), Sam Okafor (technical director), Priya Chandra (senior developer), Ellie Marsh (office manager and bookkeeper, two days a week), and now Rob Fenwick. Plus Tom Vickers, engaged as an associate rather than an employee (see the IR35 notes for how that's structured).

## Rob Fenwick — junior developer

Hired March 2026 as our first junior hire — everyone else came in at mid or senior level. £34,000 salary, standard three-month probation, 25 days holiday plus bank holidays, auto-enrolment pension at the statutory minimum contribution for year one with a review at the end of probation.

The case for a junior hire at all: we'd been turning down small, well-defined pieces of work (a WordPress-to-headless migration here, a data-cleanup script there) because nobody senior had capacity and the work didn't justify a senior rate anyway. Rob's first two months have been exactly that kind of work, supervised closely by Priya, and it's freed roughly a day a week of her time that was previously going to small jobs beneath her rate.

## Sourcing comparison

### 2023: Priya, via recruiter

When we hired Priya in 2023 we went through Harvey Nash, who charged 20% of first-year salary as a placement fee — on her £52,000 salary that was £10,400, which felt steep at the time but got us three well-screened candidates within two weeks and a hire within five. Worth it for a senior hire where the cost of a bad match is high and our own network didn't have anyone suitable at the time.

### 2026: Rob, direct

For Rob we skipped the recruiter entirely: a LinkedIn job ad (£340) plus a listing on the Bristol Tech job board (£150), total spend under £500 versus an estimated £6,800 a recruiter would have charged on his salary. It took five weeks longer to fill than the recruiter route did for Priya — ten weeks from posting to accepted offer, against five for Priya — but for a junior role where we could sensibly interview a wider, less-pre-screened pool ourselves, the trade-off was the right one. We wouldn't make the same call for another senior hire; the screening a recruiter does is worth more when the cost of getting it wrong is a £600-a-day mistake sitting in a client's codebase rather than a few weeks of extra ramp-up.

## Interview process

Two stages: a take-home exercise (a small, deliberately underspecified brief, similar in spirit to how a real client brief arrives) reviewed async by two of us, followed by a ninety-minute conversation about the exercise and a values-fit chat with Alex. We dropped a live coding round after 2023's hiring round — it measured performance-under-observation more than it measured the thing we actually cared about, and candidates consistently told us afterwards it was the part they liked least.

## Onboarding

Partial excerpt of the onboarding script Sam runs on day one, once contracts are signed:

```bash
#!/usr/bin/env bash
# onboard.sh — new starter checklist automation (partial)
# Run by Sam on day one once contracts are signed.
set -e

# Create GitHub org account with base team access
gh api orgs/kestrel-software/memberships/$1 -f role=member

# Add to 1Password shared vaults: engineering, ops
op group user add engineering "$1"
op group user add ops-readonly "$1"

# Provision Xero timesheet access (read-only for non-finance roles)
echo "Remember: Xero access is manual, Ellie handles this one."
```

## Next hire

Provisionally a mid-level developer in Q4 2026, contingent on Q3 revenue landing at or above target — see the quarterly planning notes.
