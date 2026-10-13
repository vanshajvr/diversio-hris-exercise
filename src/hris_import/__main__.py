"""
Command line report: python -m hris_import report org.csv [--json]
"""


import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .metrics import OrgMetrics, compute_metrics
from .pipeline import run_import_preview


def _pct(rate:float)->str:
    return f"{rate*100:.1f}%"

def format_report(m:OrgMetrics)->str:
    q=m.quality
    lines=[
        f"Data quality score: {q.score}/100",
        f"  validity {_pct(q.validity_rate)} | manager resolution {_pct(q.resolution_rate)} | "
        f"connectivity {_pct(q.connectivity_rate)} | completeness {_pct(q.completeness_rate)}",
        "",
        "Import funnel:",
        *(f"  {s.stage:<24}{s.count:>7}  {_pct(s.pct_of_rows):>6}" for s in m.funnel),
        "",
        f"Org: {m.headcount} employees, {m.roots} root(s), {m.managers} managers, {m.layers} layers",
        f"  depth distribution: {m.depth_distribution}",
        f"  disconnected: {', '.join(m.disconnected_employee_ids) or 'none'}",
        "",
        f"Span of control: mean {m.span.mean:.2f}, median {m.span.median}, max {m.span.max}",
        f"  distribution: {m.span.distribution}",
        f"  narrow (1 report): {len(m.span.narrow_span_manager_ids)} | wide (13+): {len(m.span.wide_span_manager_ids)}",
        "",
        "Largest orgs (direct + indirect reports):",
        *(f"  {emp_id:<12}{name:<24}{n:>5}" for emp_id,name,n in m.largest_orgs),
        "",
        "Departments:",
        *(f"  {d.department:<20}{d.headcount:>5} people  {d.managers:>3} mgrs  "
          f"{'-' if d.ics_per_manager is None else f'{d.ics_per_manager:.2f}':>5} ICs/mgr" for d in m.departments),
        "",
        "Issues by code:",
        *(f"  {code:<24}{n:>5}" for code,n in m.issue_counts.items()),
    ]
    return "\n".join(lines)

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(prog="hris-import",description="Validate an HRIS CSV and report org-health metrics.")
    sub=parser.add_subparsers(dest="command",required=True)
    report=sub.add_parser("report",help="print data-quality and org-health metrics for a CSV")
    report.add_argument("csv",type=Path)
    report.add_argument("--json",action="store_true",help="print metrics as JSON instead of text")
    args=parser.parse_args(argv)

    result=run_import_preview(args.csv.read_bytes())
    file_errors=[i for i in result.issues if i.row_number==0]
    if file_errors:
        print(f"Could not import {args.csv}: {file_errors[0].message}",file=sys.stderr)
        return 1

    metrics=compute_metrics(result)
    print(json.dumps(asdict(metrics),indent=2) if args.json else format_report(metrics))
    return 0

if __name__=="__main__":
    sys.exit(main())
