# Detection benchmark: what the validator catches, and what it can't

## Question

The validator flags missing managers, conflicts, cycles and duplicates. But a hand-written
sample with 25 rows can't tell you whether it catches *every* broken reference, or whether
it raises false alarms on messy but valid data. This benchmark measures both.

## Method

1. **Generate a clean org** (`synthetic.py`). Each manager is given a headcount budget and
   splits it unevenly across 4–8 direct reports. A 500-person org comes out with 6–7 layers,
   a median span of 4–5 and about 20% managers. Rows refer to their manager by ID only (50%),
   email only (25%) or both (25%). Rows are shuffled, so managers often appear after their reports.
2. **Inject 10 kinds of corruption** at 1% of rows per kind. Each one is labelled with the row it
   touched, the true manager, and the issue a correct validator should raise. Two kinds are
   *negative controls* that must **not** raise anything: case/whitespace noise, and a blank department.
3. **Run the real pipeline** on the CSV and compare the issues it reports with the labels.
   An issue on a row that no corruption touched counts as a false alarm.
4. **Repeat** for 100 seeds at each of three ID densities: 300 orgs, 150,000 rows and 20,046 corruptions.

ID density is the share of the ID range actually in use. 100% means sequential IDs
(EMP-1000 … EMP-1499). 10% means the same 500 people are spread across EMP-1000 … EMP-5999.

## Results

| Corruption | Injected | Flagged | Right code | Should be flagged |
|---|---:|---:|---:|---:|
| `departed_manager` ¹ | 6546 | 100.0% | 100.0% | 100.0% |
| `duplicate_row` | 1500 | 100.0% | 100.0% | 100.0% |
| `cycle_edge` | 1500 | 100.0% | 100.0% | 100.0% |
| `id_typo` | 1500 | 91.4% | 100.0% | 91.2% |
| `id_format` | 1500 | 100.0% | 100.0% | 100.0% |
| `email_typo` | 1500 | 99.7% | 100.0% | 99.7% |
| `email_domain` | 1500 | 100.0% | 100.0% | 100.0% |
| `email_mismatch` | 1500 | 100.0% | 100.0% | 100.0% |
| `cosmetic` (control) | 1500 | 0.0% | - | 0.0% |
| `missing_department` (control) | 1500 | 0.0% | - | 0.0% |

¹ Counted per affected report: one departed manager leaves several rows pointing nowhere.

**False alarms: 0** across 150,000 rows.

"Right code" is measured over corruptions that *should* be flagged. Every one of them got the
expected issue code. The gap between "Flagged" and 100% is entirely typos that land on another
real ID or email, which no validator can catch from that field alone.

### The blind spot: ID typos that land on a real ID

One-character typos in `manager_id` that raise **no issue at all**, with 95% Wilson intervals:

| ID density | `manager_id` only | `manager_id` + `manager_email` |
|---:|---:|---:|
| 100% (sequential) | **23.8%** [19.4%, 28.7%] (76/320) | 0.0% [0.0%, 2.1%] (0/180) |
| 50% | 12.4% [9.3%, 16.4%] (41/330) | 0.0% [0.0%, 2.2%] (0/170) |
| 10% | 3.6% [2.1%, 6.3%] (12/329) | 0.0% [0.0%, 2.2%] (0/171) |

## Findings

1. **The validator is complete for everything it can see.** Every detectable corruption is
   flagged with the right code, and both negative controls stay silent.
2. **With sequential IDs, about 1 in 4 ID typos silently moves an employee to the wrong manager.**
   Changing one digit of `EMP-1234` usually gives another real employee. The row looks valid,
   so it imports without warning and the org chart is wrong.
3. **Sending `manager_email` alongside `manager_id` closes the gap.** Every colliding typo became a
   `MANAGER_CONFLICT`, because the two fields now disagree. Email typos are rarely silent (4 of
   1,500), and three of those four came from the same pattern: a dropped numeric suffix
   (`dana.schmidt2@` → `dana.schmidt@`). Email schemes that add a number to tell namesakes
   apart create these collisions.
4. **Sparser IDs help, but don't fix it.** Going from 100% to 10% density cuts silent typos about
   6×, but they're still not zero.

**Product implication:** an import template that asks for *both* manager fields catches a class
of error that no amount of validation logic can catch from a single field. Check digits on
employee IDs would be the systemic fix.

## Limitations

- Typos are uniform single-character edits. Real typos cluster (adjacent keys, doubled digits),
  which probably *raises* the collision rate for numeric IDs.
- One corruption per row. Real exports can stack problems (a typo *and* a departed manager).
- The org generator is plausible, not calibrated to a real company's span/depth distribution.

## Reproduce

```bash
hris-import benchmark --seeds 100                      # this table, about 3 seconds
hris-import generate data/org.csv --size 500 --seed 42 # one org + data/org_truth.json labels
```

`tests/test_synthetic.py` asserts findings 1 and 3 on every CI run.
