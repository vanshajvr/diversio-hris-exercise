"""
Org-health and data-quality metrics computed on top of an ImportResult.
Everything here is derived from validated data only: rejected rows never reach the hierarchy.
Ratios are kept at full precision and only rounded for display.
"""


import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .models import ImportResult

#span-of-control thresholds. A single direct report usually means an unnecessary layer,
#more than 12 is beyond what most org-design guidance considers manageable.
NARROW_SPAN_MAX=1
WIDE_SPAN_MIN=13
SPAN_BUCKETS=[("1",1,1),("2-4",2,4),("5-8",5,8),("9-12",9,12),("13+",13,None)]


@dataclass
class SpanOfControl:
    managers:int=0
    mean:float=0.0
    median:float=0.0
    max:int=0
    distribution:dict[str,int]=field(default_factory=dict) #bucket label -> manager count
    narrow_span_manager_ids:list[str]=field(default_factory=list)
    wide_span_manager_ids:list[str]=field(default_factory=list)

@dataclass
class DepartmentStats:
    department:str
    headcount:int
    managers:int
    individual_contributors:int
    ics_per_manager:float|None #None when the department has no managers

@dataclass
class DataQuality:
    validity_rate:float #accepted rows / rows in file
    resolution_rate:float #resolved manager refs / employees that gave a manager ref
    connectivity_rate:float #employees reachable from a root / accepted
    completeness_rate:float #accepted with both name and department filled / accepted
    score:float #0-100, equal-weighted mean of the four rates

@dataclass
class FunnelStage:
    stage:str
    count:int
    pct_of_rows:float

@dataclass
class OrgMetrics:
    headcount:int
    roots:int
    managers:int
    individual_contributors:int
    layers:int #levels in the connected tree, a lone root is 1 layer
    depth_distribution:dict[int,int] #depth (root=0) -> headcount
    disconnected_employee_ids:list[str] #accepted, but no path up to a root
    span:SpanOfControl
    departments:list[DepartmentStats]
    largest_orgs:list[tuple[str,str,int]] #(employee_id, name, total reports incl. indirect), top 5
    quality:DataQuality
    funnel:list[FunnelStage]
    issue_counts:dict[str,int] #issue code -> count, most frequent first


def _rate(num:int,den:int)->float:
    return num/den if den else 1.0 #nothing to measure counts as fully healthy

def _tree_depths(result:ImportResult)->dict[str,int]:

    #BFS down from every root over resolved edges. O(n).
    #Cycle members and anyone below a broken manager reference never get a depth.

    children:dict[str,list[str]]=defaultdict(list)
    for e in result.accepted_employees:
        if e.resolved_manager_id:
            children[e.resolved_manager_id].append(e.employee_id)

    depth={r.employee_id:0 for r in result.roots}
    queue=[r.employee_id for r in result.roots]
    for node in queue: #queue grows while iterating, which makes this a BFS
        for child in children[node]:
            depth[child]=depth[node]+1
            queue.append(child)
    return depth

def _total_reports(result:ImportResult,depth:dict[str,int])->dict[str,int]:

    #direct + indirect reports per manager, over the connected tree only.
    #Walking employees deepest-first means every child is counted before its manager.

    manager_of={e.employee_id:e.resolved_manager_id for e in result.accepted_employees}
    subtree={emp_id:1 for emp_id in depth}
    for emp_id in sorted(depth,key=depth.get,reverse=True):
        mgr=manager_of[emp_id]
        if mgr:
            subtree[mgr]+=subtree[emp_id]
    return {emp_id:size-1 for emp_id,size in subtree.items() if size>1}

def _span(counts:dict[str,int])->SpanOfControl:
    if not counts:
        return SpanOfControl(distribution={label:0 for label,_,_ in SPAN_BUCKETS})
    values=list(counts.values())
    distribution={}
    for label,lo,hi in SPAN_BUCKETS:
        distribution[label]=sum(1 for v in values if v>=lo and (hi is None or v<=hi))
    return SpanOfControl(
        managers=len(values),
        mean=statistics.mean(values),
        median=statistics.median(values),
        max=max(values),
        distribution=distribution,
        narrow_span_manager_ids=sorted(m for m,c in counts.items() if c<=NARROW_SPAN_MAX),
        wide_span_manager_ids=sorted(m for m,c in counts.items() if c>=WIDE_SPAN_MIN),
    )

def _departments(result:ImportResult)->list[DepartmentStats]:
    headcount:Counter=Counter()
    managers:Counter=Counter()
    for e in result.accepted_employees:
        dept=e.department or "(blank)"
        headcount[dept]+=1
        if e.employee_id in result.manager_report_counts:
            managers[dept]+=1
    stats=[]
    for dept,total in headcount.items():
        ics=total-managers[dept]
        stats.append(DepartmentStats(dept,total,managers[dept],ics,
                                     ics/managers[dept] if managers[dept] else None))
    return sorted(stats,key=lambda d:(-d.headcount,d.department))

def compute_metrics(result:ImportResult)->OrgMetrics:
    employees=result.accepted_employees
    by_id={e.employee_id:e for e in employees}
    depth=_tree_depths(result)
    total_reports=_total_reports(result,depth)

    referenced=[e for e in employees if e.manager_id or e.manager_email]
    resolved=[e for e in referenced if e.resolved_manager_id]
    complete=[e for e in employees if e.employee_name and e.department]
    rates=[
        _rate(len(employees),result.total_rows),
        _rate(len(resolved),len(referenced)),
        _rate(len(depth),len(employees)),
        _rate(len(complete),len(employees)),
    ]
    #a file that failed to parse has no rows, which should not read as a perfect score
    score=round(100*statistics.mean(rates),1) if result.total_rows else 0.0

    without_manager_issue=sum(1 for e in employees if not e.manager_issue)
    stages=[
        ("Rows in file",result.total_rows),
        ("Valid identity",len(employees)),
        ("Manager reference OK",without_manager_issue),
        ("Connected to org tree",len(depth)),
    ]

    largest=sorted(total_reports.items(),key=lambda kv:(-kv[1],kv[0]))[:5]
    issue_counts=Counter(i.code.value for i in result.issues)

    return OrgMetrics(
        headcount=len(employees),
        roots=len(result.roots),
        managers=len(result.manager_report_counts),
        individual_contributors=len(employees)-len(result.manager_report_counts),
        layers=max(depth.values())+1 if depth else 0,
        depth_distribution=dict(sorted(Counter(depth.values()).items())),
        disconnected_employee_ids=sorted(e.employee_id for e in employees if e.employee_id not in depth),
        span=_span(result.manager_report_counts),
        departments=_departments(result),
        largest_orgs=[(m,by_id[m].employee_name,n) for m,n in largest],
        quality=DataQuality(*rates,score=score),
        funnel=[FunnelStage(s,n,_rate(n,result.total_rows)) for s,n in stages],
        issue_counts=dict(sorted(issue_counts.items(),key=lambda kv:(-kv[1],kv[0]))),
    )
