# 19. Limitations and assumptions

Assumptions: every assumed value has an ID in docs/09 (ASM-..., DEC-..., AMB-...), labelled ASSUMPTION
(illustrative synthetic). Nothing here is real company policy. ALL DATA IS SYNTHETIC.

## Known limitations and future work

| Item | Effect | Where recorded |
|---|---|---|
| 8B-2 deferred: resubmission rounds and cancellations are not in the dataset (services exist and are tested) | every request has one round; no CANCELLED rows | docs/09 13.6 |
| 8B-2 deferred: S11 / S12 / S18 plants (self-approval, unauthorized approver, repeated submission) | M9 not measurable; acceptance 11 partial | docs/09 13.6, docs/12 |
| 8B-2 deferred: per-round ground truth (migration 0005 ground_truth.record_round_expectation) | evaluation is per request, final round | docs/09 13.4, 16 |
| Audit hash chain not implemented | audit rows are append-only (triggers) but not tamper-evident | DEC-P8-10 |
| Leave and budget ledger postings have no audit_event rows | ledgers are their own append-only history | DEC-P8-09 |
| First submissions accept no Idempotency-Key | a retried POST creates a second request | AMB-P9-01 |
| Token roles are not re-checked against user_role on each call | role changes apply at the next login | AMB-P9-02 |
| No receipt upload through the API | receipts exist only in the generated data | docs/09 14 |
| Leave utilisation (spec 20) not shown | dashboard shows days approved instead | AMB-CP-02 |
| Business-day variants of M14 and M18 not computed | calendar days only | docs/08 section 7 |
| Every rejection in the dataset is planted | the natural rejection rate (M17 without planted anomalies) is 0 | docs/12 |
| Results on a synthetic benchmark | 100% detection shows the rules are implemented as documented, not real-world accuracy | docs/08 section 7, docs/12 |
| Simulated authentication | not production security | amendment F2 |
