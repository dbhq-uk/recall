---
title: VAT scheme, invoicing and payment terms
tags: [finance, vat, invoicing, compliance]
---

# VAT, Invoicing and Payment Terms

## Company details

Kestrel Software Consulting Ltd, company number 09456821, incorporated 14 May 2019. Registered office: 14 Foundry Row, Bristol, BS1 6QN. SIC code 62012 (business and domestic software development). VAT registered since incorporation, VAT number GB 245 8891 07.

## VAT scheme history

### Flat Rate Scheme, 2019–2025

We registered under the VAT Flat Rate Scheme from day one, in the "Computer and IT consultancy or data processing" category, paying HMRC at 14.5% of gross turnover rather than reconciling input and output VAT line by line. For a business with almost no reclaimable input VAT beyond the odd laptop purchase, this was simpler and, most years, slightly better for cash flow than standard VAT accounting.

### Leaving the Flat Rate Scheme, April 2025

Naomi at Fernbank flagged something during the 2024 year-end review that we'd genuinely missed: because our goods spend has always been a tiny fraction of turnover, we likely met HMRC's definition of a "limited cost business" under the anti-avoidance rules introduced in 2017, which would mean applying a 16.5% rate rather than the 14.5% sector rate — not the number we'd been using. Rather than unpick years of returns, Fernbank's advice was to draw a line, correct forward from the current period, and move off the Flat Rate Scheme entirely rather than keep tracking the limited-cost test quarter by quarter.

We timed the move deliberately: we'd already been planning a laptop and monitor refresh for the whole team, and under standard VAT accounting that capex becomes reclaimable input VAT, which it isn't under the Flat Rate Scheme. We brought the refresh forward to March 2025 — £16,800 including installation and disposal of the old kit — and switched to standard accounting from 1 April 2025, so the input VAT on that spend landed in the first return under the new scheme rather than being wasted under the old one. Small piece of tax-timing housekeeping, but it covered most of Fernbank's fee for sorting the whole thing out.

### Standard VAT accounting now

We reconcile output VAT on sales invoices against input VAT on purchases each quarter through Xero, filed via Making Tax Digital. It's more admin than the Flat Rate Scheme was, but with the team growing and software licence costs (GitHub Enterprise, AWS, Xero itself) all carrying reclaimable VAT, it's the better structure going forward, not just a one-off correction.

## Invoice numbering

Format: `KSW-YYYY-NNNN` — company prefix, four-digit year, four-digit sequence reset to `0001` on 1 January each year. Example: `KSW-2026-0034`. Sequence numbers are never reused or skipped, even for voided invoices, so a gap in the sequence is always investigated rather than assumed to be nothing.

## Payment terms

Standard terms are 30 days net from invoice date, stated on every invoice template. For new clients without a trading history with us, the first invoice is due on signature rather than on 30-day terms — a habit picked up after one early client took eleven weeks to pay a first invoice and nearly caused a cash-flow problem.

Late payment interest, where we've had to invoke it (twice, both eventually resolved without needing to go further), is calculated under the Late Payment of Commercial Debts (Interest) Act 1998: the statutory rate of 8% plus the Bank of England base rate at the time the debt became overdue, plus a fixed compensation sum depending on the invoice value.

## Debtors query

Ellie runs this against the Xero data export on the 1st of each month to flag anything ageing before it becomes a real problem:

```sql
-- monthly-debtors.sql
-- Flags invoices more than 45 days past due.
SELECT invoice_ref, client_name, amount_due, due_date
FROM sales_invoices
WHERE status = 'AUTHORISED'
  AND due_date < CURRENT_DATE - INTERVAL '45 days'
ORDER BY due_date ASC;
```
