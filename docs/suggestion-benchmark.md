# Suggested fixes: how often they're right, and when they should stay quiet

## Question

When a manager reference is broken, can the importer propose the intended manager, so that an HR
admin confirms a fix instead of researching it? Proposing the **wrong** manager is worse than
proposing nothing: it looks authoritative and gets accepted. So the bar is high precision first,
then as much coverage as precision allows.

## The engine (`suggestions.py`)

Rule-based and explainable. Every suggestion carries a reason and a one-line explanation the
admin can check:

| Rule | Evidence |
|---|---|
| `email_resolves` | `manager_id` is broken but `manager_email` names a real person |
| `id_format` | Same ID once case, spaces and punctuation are ignored (`emp 1234` → `EMP-1234`) |
| `email_domain` | Same mailbox on another domain (old `acme.io` exports) |
| `conflict_email_wrong` / `conflict_id_typo` | The two fields name different people; the ID's edit distance and the department decide which field is wrong |
| `id_typo` / `email_typo` | Exactly one real employee is one edit away, in the same department |
| `typo_other_department` | One edit away, but in a different department |
| `typo_tiebreak` | Several one-edit candidates; exactly one is in the same department and already manages people |

The engine **abstains** in three situations:
- **`manager_missing_from_file`:** several rows point at the same absent value. That's most likely a
  person missing from the export (for example, they left), so it says so instead of guessing a neighbour.
- **`ambiguous`:** several candidates and nothing to separate them.
- **`no_candidate`:** nobody is close.

It never proposes a manager that would create a reporting cycle.

## Method

- Same synthetic orgs and labels as the [detection benchmark](detection-benchmark.md): 100 seeds ×
  3 ID densities. That gives 11,272 broken manager references: 7,366 where the true manager is in the
  file, and 3,906 where they are not (departed managers), for which the right answer is *no suggestion*.
- **Precision** = correct proposals / proposals. **Coverage** = correct proposals / references whose
  manager is in the file. A proposal on a departed manager's row is always wrong.
- **Held-out calibration.** Each rule's confidence is its measured precision on 300 *other* orgs
  (seeds 10000+), capped at 0.99. Everything below is reported on orgs the calibration never saw.
  A test fails if the stated confidences drift from re-measured ones, so they can't go stale.

## Results

### Calibration: does a stated 0.96 mean right 96% of the time?

| Rule | Proposals | Stated confidence | Observed precision (95% CI) |
|---|---:|---:|---:|
| `email_resolves` | 921 | 0.99 | 100.0% [99.6%, 100.0%] |
| `id_format` | 998 | 0.99 | 100.0% [99.6%, 100.0%] |
| `email_domain` | 1500 | 0.99 | 100.0% [99.7%, 100.0%] |
| `conflict_email_wrong` | 1495 | 0.99 | 100.0% [99.7%, 100.0%] |
| `conflict_id_typo` | 52 | 0.99 | 100.0% [93.1%, 100.0%] |
| `id_typo` | 258 | 0.96 | 95.7% [92.5%, 97.6%] |
| `email_typo` | 1459 | 0.96 | 98.2% [97.4%, 98.8%] |
| `typo_tiebreak` | 800 | 0.60 | 59.1% [55.7%, 62.5%] |
| `typo_other_department` | 151 | 0.28 | 31.8% [24.9%, 39.6%] |

Every stated confidence falls inside or just below its held-out interval. The numbers mean what they say.

### Choosing the operating point

| Confidence threshold | Precision | Coverage | Wrong proposals for departed managers |
|---:|---:|---:|---:|
| 0.00 (propose everything) | 93.9% | 97.3% | 463 of 3,906 |
| 0.50 | 95.1% | 96.6% | 360 of 3,906 |
| **0.80 (default)** | **99.4%** | **90.2%** | **37 of 3,906** |
| 0.97 | 100.0% | 67.4% | 0 of 3,906 |

At **0.80**, 9 in 10 fixable references get a correct one-click fix, and fewer than 1% of departed
managers' rows get a wrong one. Anything below 0.80 is shown as *needs review* (a candidate with its
evidence), not as a proposed fix.

### By corruption kind (at 0.80)

| Corruption | Issues | Proposed | Precision | Coverage |
|---|---:|---:|---:|---:|
| `departed_manager` | 3906 | 37 | 0.0% | should abstain: 99.1% did |
| `id_typo` | 1370 | 718 | 100.0% | 52.4% |
| `id_format` | 1500 | 1500 | 100.0% | 100.0% |
| `email_typo` | 1496 | 1433 | 100.0% | 95.8% |
| `email_domain` | 1500 | 1500 | 100.0% | 100.0% |
| `email_mismatch` | 1500 | 1495 | 100.0% | 99.7% |

### What each rule is worth (ablations at 0.80)

| Variant | Precision | Coverage | Wrong proposals for departed managers |
|---|---:|---:|---:|
| Full engine | 99.4% | 90.2% | 37 |
| Without the department signal | 97.4% | 90.6% | 140 |
| Without missing-manager detection | 98.7% | 90.3% | 86 |
| Without the typo tie-break | 99.4% | 90.2% | 37 |

## Findings

1. **Formatting and domain drift are solved problems.** `id_format`, `email_domain` and
   `email_resolves` are 100% precise with full coverage. These are also the most common real-world
   causes, and they're exactly what an admin would otherwise fix one row at a time.
2. **The department is the strongest guard against confident mistakes.** Without it, wrong proposals
   for departed managers go up 3.8× (37 → 140), and `conflict_id_typo` drops to 61% precision during
   development, because with sequential IDs the wrong email's owner is often one digit from the real manager.
3. **"Several rows share one missing value" is a reliable departure signal.** It caught 2,745 departed-manager
   rows. The 5 times it fired on a recoverable reference, two independent typos had produced the same broken value.
4. **Sequential-ID typos are the hard case: 100% precise but only 52% covered.** A typo like `EMP-118`
   was one edit from 23 real IDs in one example org. The engine sends these to review instead of guessing. That's
   the same root cause as the [detection blind spot](detection-benchmark.md), and the same fix applies:
   collect `manager_email` too.
5. **The tie-break only helps the review queue.** At 0.80 it changes nothing (it's 59% precise, so it
   sits below the threshold), but it puts the likeliest candidate first for the reviewer.

## Limitations

- **Departments are inherited strictly in the synthetic orgs,** so the department signal is cleaner
  here than in real data, where matrix reporting exists. Expect it to be less decisive in practice.
- **The `departed_manager` cases where one stale row remains are inherently ambiguous by ID.** The 37
  wrong proposals at 0.80 are single stale rows whose ID is one digit from a same-department colleague.
  Nothing in the row can tell those apart from a typo.
- **No LLM.** Every rule here is cheap, deterministic and checkable. An LLM would be worth testing only
  on the `ambiguous` bucket (541 rows), against the same labels.

## Reproduce

```bash
hris-import suggest data/synthetic_org_500.csv   # suggestions for one file
hris-import benchmark --suggestions --seeds 100  # these tables, about 18 seconds
```
