# PRD: HRIS import review queue

**Status:** built as a prototype in this repo. The metrics and experiment below are a proposal.
**Evidence:** [detection benchmark](detection-benchmark.md) and [suggestion benchmark](suggestion-benchmark.md).

## Problem

People-analytics products like Diversio are only as good as the org chart they're given. That chart
arrives as an HRIS export, and exports are messy: a manager has left, IDs are written in a different
format, an old email domain is still in the file, someone is listed twice.

Today, a broken reference means one of two things. Either the import fails, and the customer goes back
and forth with support over a list of row numbers. Or it quietly succeeds, and part of the org is missing
from every downstream analysis. Both outcomes hurt trust at onboarding, the moment it matters most.

The benchmarks show how big this is. At a 1% corruption rate per kind, a synthetic 500-person org
keeps on average only **66% of its people connected to the CEO**. In 1 org out of 10, fewer than 43%
stay connected (100 orgs measured). The damage is lopsided: one broken link high in the tree cuts off
everyone below it.

## Users

| User | Goal | Today |
|---|---|---|
| **HR / People Ops admin** at the customer (primary) | Get a clean org into the product with the least back-and-forth | Fixes rows one by one in a spreadsheet from an error list |
| **Customer success / onboarding** at Diversio | Get the customer to their first dashboard quickly | Triages import tickets by hand |
| **Analysts** downstream | Trust that the hierarchy is complete | Can't see which teams were silently dropped |

## Goals and non-goals

**Goals**
1. Show the admin **what is broken, in order of impact**, not in row order.
2. **Propose fixes only when they're very likely right,** and say why.
3. Make the result **one download**: a corrected CSV that changes only the cells the admin approved.

**Non-goals (v1)**
- Writing back to the customer's HRIS. The admin stays the source of truth.
- Storing uploaded files. The prototype is stateless: the file travels with the form.
- Fixing reporting loops automatically. They need a human decision (see "Open questions").

## Solution

1. **Upload:** run the validator and compute the data quality score, import funnel and org-health metrics.
2. **Review queue:** one item per decision, sorted by **people affected**, meaning the employee plus
   everyone below them who is cut off from the org chart. Rows pointing at the same absent manager are
   grouped ("Manager EMP-1075 is not in the file but 3 people report to them"). Reporting loops are one item.
3. **Three tiers:**
   - **Confident** (≥ 0.80 calibrated confidence): pre-selected.
   - **Needs review:** a candidate with its evidence, not pre-selected.
   - **Manual:** no candidate; the admin decides.
4. **Projected impact** before committing: "Accepting the 22 pre-selected fixes reconnects 37 people and
   raises data quality from 93.8 to 96.8."
5. **Download the corrected CSV.**

### Why 0.80

From the held-out suggestion benchmark:

| Threshold | Precision | Coverage | Wrong proposals for departed managers |
|---:|---:|---:|---:|
| 0.50 | 95.1% | 96.6% | 360 of 3,906 |
| **0.80** | **99.4%** | **90.2%** | **37 of 3,906** |
| 0.97 | 100.0% | 67.4% | 0 of 3,906 |

A pre-selected fix that's wrong is worse than no fix: it gets accepted without a second look. Going from
0.50 to 0.80 gives up 6 points of coverage and cuts wrong proposals by 90%. Going higher costs another
23 points of coverage to remove the last 37. Those are mostly single stale rows that nothing in the data
can tell apart from a typo.

## Success metrics

| Metric | Definition | Why |
|---|---|---|
| **North star: first-pass clean import rate** | Share of import sessions where the *second* upload has zero manager issues | Measures whether the admin could fix everything in one go |
| Time to clean import | Minutes from first upload to a clean upload | The cost the customer actually feels |
| Suggestion acceptance rate | Accepted / shown, per tier | If confident fixes get unticked often, the threshold is wrong for real data |
| People reconnected per session | From the projection, after the admin's choices | Value delivered, in the customer's terms |

**Guardrail:** **post-import manager corrections**, meaning changes to a manager within 30 days of import
that undo an accepted suggestion. This is the real-world precision of the engine. If it rises above about
1% of accepted fixes, raise the threshold.

## Instrumentation

Events are emitted as JSON log lines from `web.py`. The first two exist in the prototype.

| Event | Fields | Answers |
|---|---|---|
| `import_previewed` | rows, issues, queue_auto, queue_review, queue_manual, quality_score, projected_score | Funnel entry; how messy files really are |
| `fixes_applied` | fixes, rows | Acceptance; whether people use the download |
| `suggestion_decided` *(proposed)* | reason, tier, confidence, accepted | Per-rule acceptance, which recalibrates `CONFIDENCE` on real data |
| `import_completed` *(proposed)* | session_id, uploads, minutes, final_issues | North star and time to clean import |

## Experiment

**Design:** randomize import sessions between the current error list (control) and the review queue
(treatment). Randomize by customer account rather than session, so one admin never sees both.

**Primary metric:** first-pass clean import rate.

**Sample size:** assuming a 40% baseline and wanting to detect a lift to 50% (α = 0.05, power 0.8,
two-sided), that's **388 sessions per arm**. A lift to 55% needs 173 per arm. The baseline is an
assumption; measure it from `import_previewed` / `import_completed` before launching.

**The realistic constraint:** a B2B product may not see 776 onboarding imports in a reasonable time. If
volume is low:
- Use **time to clean import** as the primary metric. It's continuous, so it needs far fewer sessions.
- Or **ship to everyone with a holdout**, and compare against a pre-launch baseline with the same mix
  of customer sizes.
- Either way, the guardrail is tracked per accepted fix, so it gets plenty of data quickly.

## Launch plan

1. **Internal:** customer success uses it on real tickets, logging `suggestion_decided`.
2. **Recalibrate** `CONFIDENCE` on those decisions. The synthetic calibration is a starting point, not
   ground truth (synthetic departments are cleaner than real ones).
3. **Beta** to new customers in onboarding, then the experiment above.

## Recommendations outside the tool

The benchmarks point to two cheaper wins than any algorithm:

1. **Ask for both `manager_id` and `manager_email` in the import template.** With sequential IDs,
   **19.7%** of single-character ID typos silently attach someone to the wrong manager when only the ID
   is given. With both fields, **0%**: the fields disagree, so the error is caught.
2. **Flag customers whose employee IDs are sequential and have no check digit.** They're the ones most
   exposed to silent errors, so they're worth a review of their first import.

## Open questions

- **Reporting loops:** which edge should break? The most recently changed one (needs HRIS history) or
  the one that keeps the most people connected? Left manual in v1.
- **Matrix orgs:** the department signal assumes reports usually sit in their manager's department.
  How often is that false for real customers? The `suggestion_decided` logs will show this.
- **Should the corrected file be imported directly,** skipping the second upload? That's faster, but it
  removes the admin's last check.
