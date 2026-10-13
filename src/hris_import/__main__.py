"""
Command line entry point:
  hris-import report org.csv [--json]        data-quality and org-health metrics
  hris-import generate out.csv [--size 500]  synthetic org with labelled corruptions
  hris-import benchmark [--seeds 20]         score the validator against synthetic orgs
"""


import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .evaluation import format_benchmark, run_benchmark
from .metrics import OrgMetrics, compute_metrics
from .pipeline import run_import_preview
from .synthetic import generate_org


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

def _report(args)->int:
    result=run_import_preview(args.csv.read_bytes())
    file_errors=[i for i in result.issues if i.row_number==0]
    if file_errors:
        print(f"Could not import {args.csv}: {file_errors[0].message}",file=sys.stderr)
        return 1

    metrics=compute_metrics(result)
    print(json.dumps(asdict(metrics),indent=2) if args.json else format_report(metrics))
    return 0

def _generate(args)->int:
    org=generate_org(args.size,seed=args.seed,corruption_rate=args.corruption_rate,id_density=args.id_density)
    args.out.write_bytes(org.csv_bytes)
    truth=args.out.with_name(args.out.stem+"_truth.json")
    truth.write_text(json.dumps([asdict(c) for c in org.corruptions],indent=2)+"\n")
    print(f"Wrote {args.out} (a {args.size}-person org) and {truth} ({len(org.corruptions)} labelled corruptions)")
    return 0

def _benchmark(args)->int:
    result=run_benchmark(args.size,seeds=args.seeds,densities=tuple(args.densities))
    print(format_benchmark(result))
    return 0

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(prog="hris-import",description="Validate an HRIS CSV and report org-health metrics.")
    sub=parser.add_subparsers(dest="command",required=True)

    report=sub.add_parser("report",help="print data-quality and org-health metrics for a CSV")
    report.add_argument("csv",type=Path)
    report.add_argument("--json",action="store_true",help="print metrics as JSON instead of text")
    report.set_defaults(handler=_report)

    generate=sub.add_parser("generate",help="write a synthetic org CSV with labelled corruptions")
    generate.add_argument("out",type=Path,help="CSV path; ground truth goes next to it as <name>_truth.json")
    generate.add_argument("--size",type=int,default=500)
    generate.add_argument("--seed",type=int,default=0)
    generate.add_argument("--corruption-rate",type=float,default=0.01,help="share of rows per corruption kind")
    generate.add_argument("--id-density",type=float,default=1.0,help="share of the id range in use (1.0 = sequential)")
    generate.set_defaults(handler=_generate)

    bench=sub.add_parser("benchmark",help="score the validator against many synthetic orgs")
    bench.add_argument("--size",type=int,default=500)
    bench.add_argument("--seeds",type=int,default=20)
    bench.add_argument("--densities",type=float,nargs="+",default=[1.0,0.5,0.1])
    bench.set_defaults(handler=_benchmark)

    args=parser.parse_args(argv)
    return args.handler(args)

if __name__=="__main__":
    sys.exit(main())
