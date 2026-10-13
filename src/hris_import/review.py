"""
Turns issues and suggestions into a review queue an HR admin can work through, ordered by impact.

Impact = how many people the issue cuts off from the org chart: the employee plus everyone below
them. One broken link under a VP disconnects a whole department, while a broken link on an individual
contributor disconnects one person, so row order is the wrong order to fix things in.
"""


import csv
import io
from collections import defaultdict
from dataclasses import dataclass

from .metrics import compute_metrics
from .models import Employee, ImportResult, IssueCode
from .pipeline import run_import_preview
from .suggestions import DEFAULT_THRESHOLD, MISSING_MANAGER, Suggestion, suggest_fixes

AUTO="auto" #confident fix, pre-selected
REVIEW="review" #a candidate worth checking, not pre-selected
MANUAL="manual" #nothing to propose; someone has to decide
_TIER_ORDER={AUTO:0,REVIEW:1,MANUAL:2}


@dataclass
class ReviewItem:
    key:str #stable id used by the web form
    employee_ids:list[str]
    row_numbers:list[int]
    issue_code:IssueCode
    title:str
    people_affected:int #employees cut off from the org chart until this is resolved
    tier:str
    suggestion:Suggestion|None=None #set for single-row manager issues

@dataclass
class Projection:
    fixes:int
    score_before:float
    score_after:float
    connected_before:int
    connected_after:int

@dataclass
class ReviewQueue:
    items:list[ReviewItem]
    projection:Projection|None #what accepting every AUTO fix would do


def _children(employees:list[Employee])->dict[str,list[str]]:
    children:dict[str,list[str]]=defaultdict(list)
    for e in employees:
        if e.resolved_manager_id:
            children[e.resolved_manager_id].append(e.employee_id)
    return children

def _subtree_size(children:dict[str,list[str]],root:str,exclude:frozenset[str]=frozenset())->int:
    #root plus everyone below it; the seen-set also makes this safe on reporting loops
    seen={root}
    stack=[root]
    while stack:
        for c in children[stack.pop()]:
            if c not in seen and c not in exclude:
                seen.add(c)
                stack.append(c)
    return len(seen)

def _cycles(result:ImportResult)->list[list[str]]:
    manager_of={e.employee_id:e.resolved_manager_id for e in result.accepted_employees}
    seen:set[str]=set()
    cycles=[]
    for start in sorted(result.cyclic_employee_ids):
        if start in seen:
            continue
        loop=[start]
        node=manager_of[start]
        while node!=start:
            loop.append(node)
            node=manager_of[node]
        seen.update(loop)
        cycles.append(loop)
    return cycles

def _title(e:Employee)->str:
    name=e.employee_name or e.employee_id
    if e.manager_issue.code==IssueCode.MANAGER_CONFLICT:
        return f"{name}: manager_id {e.manager_id} and manager_email {e.manager_email} name different people"
    if e.manager_issue.code==IssueCode.SELF_MANAGED:
        return f"{name} is listed as their own manager"
    return f"{name}: manager {e.manager_id or e.manager_email} is not in the file"

def build_review_queue(result:ImportResult,suggestions:list[Suggestion]|None=None,
                       threshold:float=DEFAULT_THRESHOLD)->list[ReviewItem]:
    suggestions=suggest_fixes(result) if suggestions is None else suggestions
    by_id={e.employee_id:e for e in result.accepted_employees}
    children=_children(result.accepted_employees)
    items:list[ReviewItem]=[]

    #rows that all point at the same absent manager are one decision, not several
    missing:dict[str,list[Suggestion]]=defaultdict(list)
    for s in suggestions:
        if s.reason==MISSING_MANAGER:
            e=by_id[s.employee_id]
            missing[e.manager_id or e.manager_email].append(s)
            continue
        e=by_id[s.employee_id]
        if s.suggested_manager_id:
            tier=AUTO if s.confidence>=threshold else REVIEW
        else:
            tier=MANUAL
        items.append(ReviewItem(s.employee_id,[s.employee_id],[s.row_number],s.issue_code,_title(e),
                                _subtree_size(children,s.employee_id),tier,s))

    for value,group in missing.items():
        items.append(ReviewItem(f"missing:{value}",[s.employee_id for s in group],[s.row_number for s in group],
                                IssueCode.MANAGER_NOT_FOUND,
                                f"Manager {value} is not in the file but {len(group)} people report to them",
                                sum(_subtree_size(children,s.employee_id) for s in group),MANUAL))

    for loop in _cycles(result):
        members=frozenset(loop)
        names=" → ".join(by_id[i].employee_name or i for i in [*loop,loop[0]])
        below=sum(_subtree_size(children,i,members)-1 for i in loop) #people hanging under the loop, outside it
        items.append(ReviewItem(f"cycle:{loop[0]}",loop,sorted(by_id[i].row_number for i in loop),
                                IssueCode.REPORTING_CYCLE,f"Reporting loop: {names}",len(loop)+below,MANUAL))

    return sorted(items,key=lambda i:(-i.people_affected,_TIER_ORDER[i.tier],min(i.row_numbers)))


def apply_fixes(file_bytes:bytes,result:ImportResult,fixes:dict[str,str])->bytes:

    #rewrite the source CSV with the chosen manager for each fixed employee.
    #Both manager fields are set to the same person, so the fixed row can't conflict again.
    #Every other cell, column and row is left exactly as it was.

    by_id={e.employee_id:e for e in result.accepted_employees}
    reader=csv.reader(io.StringIO(file_bytes.decode("utf-8-sig")))
    header=next(reader)
    col={h.strip().lower():i for i,h in enumerate(header)}
    out=io.StringIO()
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(header)
    for row in reader:
        emp_id=row[col["employee_id"]].strip() if len(row)>col["employee_id"] else ""
        mgr=by_id.get(fixes.get(emp_id,""))
        if mgr and emp_id in by_id:
            row+=[""]*(len(header)-len(row))
            row[col["manager_id"]]=mgr.employee_id
            row[col["manager_email"]]=mgr.email
        writer.writerow(row)
    return out.getvalue().encode("utf-8")

def auto_fixes(items:list[ReviewItem])->dict[str,str]:
    return {i.employee_ids[0]:i.suggestion.suggested_manager_id for i in items if i.tier==AUTO}

def review(file_bytes:bytes,threshold:float=DEFAULT_THRESHOLD)->tuple[ImportResult,ReviewQueue]:
    result=run_import_preview(file_bytes)
    if result.total_rows==0:
        return result,ReviewQueue([],None)
    items=build_review_queue(result,threshold=threshold)
    fixes=auto_fixes(items)
    projection=None
    if fixes:
        before=compute_metrics(result)
        after=compute_metrics(run_import_preview(apply_fixes(file_bytes,result,fixes)))
        projection=Projection(len(fixes),before.quality.score,after.quality.score,
                              before.funnel[-1].count,after.funnel[-1].count)
    return result,ReviewQueue(items,projection)
