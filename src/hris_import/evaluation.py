"""
Scores the validator against synthetic orgs with known corruptions.
Two questions: did every corruption get flagged (with the right code), and did anything get
flagged that no corruption explains (a false alarm)?
"""


import math
from collections import defaultdict
from dataclasses import dataclass

from .models import ImportResult, IssueCode, RowIssue
from .pipeline import run_import_preview
from .synthetic import ID_TYPO, KINDS, Corruption, SyntheticOrg, generate_org


@dataclass
class DetectionOutcome:
    corruption:Corruption
    detected:bool #any issue raised on the corrupted row
    expected_code_raised:bool #the specific issue a correct validator should raise

@dataclass
class DetectionReport:
    outcomes:list[DetectionOutcome]
    unexplained_issues:list[RowIssue] #issues on rows no corruption touched


def _cycle_members(result:ImportResult,start:str)->set[str]:
    manager_of={e.employee_id:e.resolved_manager_id for e in result.accepted_employees}
    members={start}
    node=manager_of[start]
    while node!=start:
        members.add(node)
        node=manager_of[node]
    return members

def evaluate_detection(org:SyntheticOrg,result:ImportResult)->DetectionReport:
    codes_by_row:dict[str,set[IssueCode]]=defaultdict(set)
    for issue in result.issues:
        codes_by_row[issue.employee_id].add(issue.code)

    outcomes=[]
    for c in org.corruptions:
        codes=codes_by_row.get(c.employee_id,set())
        outcomes.append(DetectionOutcome(c,bool(codes),c.expected_issue in codes if c.expected_issue else False))

    touched={c.employee_id for c in org.corruptions}|{i for c in org.corruptions for i in c.affected_ids}
    unexplained=[]
    for issue in result.issues:
        if issue.employee_id in touched:
            continue
        #a typo that lands on a real id can close a loop; the whole loop is explained by that typo
        if issue.code==IssueCode.REPORTING_CYCLE and _cycle_members(result,issue.employee_id)&touched:
            continue
        unexplained.append(issue)
    return DetectionReport(outcomes,unexplained)


@dataclass
class KindSummary:
    kind:str
    injected:int=0
    detected:int=0
    expected_code:int=0
    expects_issue:int=0 #corruptions where the ground truth says an issue should be raised

@dataclass
class BenchmarkResult:
    runs:int
    rows:int
    by_kind:list[KindSummary]
    id_typo_silent:dict[tuple[float,str],tuple[int,int]] #(id density, ref style) -> (silent, total)
    unexplained_issues:int

def run_benchmark(size:int=500,seeds:int=20,densities:tuple[float,...]=(1.0,0.5,0.1),
                  corruption_rate:float=0.01)->BenchmarkResult:
    by_kind={k:KindSummary(k) for k in KINDS}
    silent:dict[tuple[float,str],list[int]]=defaultdict(lambda:[0,0])
    unexplained=0
    rows=0
    for density in densities:
        for seed in range(seeds):
            org=generate_org(size,seed=seed,corruption_rate=corruption_rate,id_density=density)
            result=run_import_preview(org.csv_bytes)
            report=evaluate_detection(org,result)
            rows+=result.total_rows
            unexplained+=len(report.unexplained_issues)
            for o in report.outcomes:
                s=by_kind[o.corruption.kind]
                s.injected+=1
                s.detected+=o.detected
                s.expected_code+=o.expected_code_raised
                s.expects_issue+=o.corruption.expected_issue is not None
                if o.corruption.kind==ID_TYPO:
                    silent[(density,o.corruption.ref_style)][0]+=not o.detected
                    silent[(density,o.corruption.ref_style)][1]+=1
    return BenchmarkResult(len(densities)*seeds,rows,list(by_kind.values()),
                           {k:(v[0],v[1]) for k,v in sorted(silent.items(),reverse=True)},unexplained)

def _pct(num:int,den:int)->str:
    return f"{100*num/den:.1f}%" if den else "-"

def wilson_interval(successes:int,total:int,z:float=1.96)->tuple[float,float]:
    #95% interval for a proportion; unlike the normal approximation it stays inside [0,1] near 0% and 100%
    if total==0:
        return (0.0,1.0)
    p=successes/total
    centre=(p+z*z/(2*total))/(1+z*z/total)
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return (max(0.0,centre-half),min(1.0,centre+half))

def format_benchmark(b:BenchmarkResult)->str:
    lines=[
        f"{b.runs} synthetic orgs, {b.rows:,} rows, {sum(k.injected for k in b.by_kind):,} injected corruptions",
        "",
        "| Corruption | Injected | Flagged | Right code | Should be flagged |",
        "|---|---:|---:|---:|---:|",
    ]
    for k in b.by_kind:
        lines.append(f"| `{k.kind}` | {k.injected} | {_pct(k.detected,k.injected)} | "
                     f"{_pct(k.expected_code,k.expects_issue)} | {_pct(k.expects_issue,k.injected)} |")
    lines+=[
        "",
        f"Issues not explained by any injected corruption (false alarms): {b.unexplained_issues}",
        "",
        "One-character typos in manager_id that go completely unflagged (95% Wilson interval):",
        "",
        "| ID density | manager_id only | manager_id + manager_email |",
        "|---:|---:|---:|",
    ]
    for density in sorted({d for d,_ in b.id_typo_silent},reverse=True):
        cells=[]
        for style in ("id","both"):
            silent,total=b.id_typo_silent.get((density,style),(0,0))
            lo,hi=wilson_interval(silent,total)
            cells.append(f"{_pct(silent,total)} [{lo:.1%}, {hi:.1%}] ({silent}/{total})")
        lines.append(f"| {density:.0%} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines)
