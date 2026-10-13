"""
Suggested fixes for broken manager references.

Rule-based and explainable on purpose: every suggestion says which evidence it used, and the
engine abstains when the evidence is ambiguous. Each rule's confidence is
its measured precision on calibration data, and the benchmark reports results on separate orgs.
"""


import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import Employee, ImportResult, IssueCode

#reasons, also the keys of the calibration table in the benchmark
EMAIL_RESOLVES="email_resolves" #manager_id broken but manager_email names a real person
ID_RESOLVES="id_resolves" #the reverse
ID_FORMAT="id_format" #same id once case, spaces and punctuation are ignored
EMAIL_DOMAIN="email_domain" #same mailbox name on a different domain
MISSING_MANAGER="manager_missing_from_file" #several rows point at the same absent person: don't guess
ID_TYPO="id_typo" #exactly one real id is one edit away
EMAIL_TYPO="email_typo" #exactly one real mailbox is one edit away
TYPO_OTHER_DEPT="typo_other_department" #single one-edit candidate, but in a different department
TYPO_TIEBREAK="typo_tiebreak" #several one-edit candidates, one clearly fits best (department, already a manager)
CONFLICT_ID_TYPO="conflict_id_typo" #manager_id is one edit from the email person's id: the id was mistyped
CONFLICT_EMAIL_WRONG="conflict_email_wrong" #otherwise trust the id, the email belongs to someone else
AMBIGUOUS="ambiguous"
NO_CANDIDATE="no_candidate"

#Observed precision of each rule on 300 calibration orgs (evaluation.calibrate_confidence, seeds 10000+),
#capped at 0.99: a finite sample never justifies certainty. Benchmarks report on different seeds.
#ID_RESOLVES never occurs in the synthetic data, so its value is a prior, not a measurement.
CONFIDENCE={ID_FORMAT:0.99,EMAIL_RESOLVES:0.99,EMAIL_DOMAIN:0.99,CONFLICT_ID_TYPO:0.99,CONFLICT_EMAIL_WRONG:0.99,
            ID_TYPO:0.96,EMAIL_TYPO:0.96,ID_RESOLVES:0.95,TYPO_TIEBREAK:0.60,TYPO_OTHER_DEPT:0.28}


@dataclass
class Suggestion:
    employee_id:str
    row_number:int
    issue_code:IssueCode
    suggested_manager_id:str|None #None = no suggestion (abstained, or the manager isn't in the file)
    confidence:float
    reason:str
    explanation:str

@dataclass
class SuggestOptions:
    detect_missing_manager:bool=True #treat a missing value shared by several rows as a real absent person
    tiebreak:bool=True #pick among several typo candidates using department / manager signals
    department_signal:bool=True #trust a typo/conflict match less when the departments don't line up


def edits1(value:str,alphabet:str)->set[str]:
    #every string one Damerau edit away (delete, transpose, substitute, insert).
    #Generating variants and looking them up is O(len*alphabet) per reference instead of O(n) comparisons.
    splits=[(value[:i],value[i:]) for i in range(len(value)+1)]
    deletes={a+b[1:] for a,b in splits if b}
    transposes={a+b[1]+b[0]+b[2:] for a,b in splits if len(b)>1}
    replaces={a+c+b[1:] for a,b in splits if b for c in alphabet}
    inserts={a+c+b for a,b in splits for c in alphabet}
    return (deletes|transposes|replaces|inserts)-{value}

def _id_key(value:str)->str:
    return re.sub(r"[^0-9a-z]","",value.lower())


class _Index:
    def __init__(self,result:ImportResult):
        self.employees=result.accepted_employees
        self.by_id={e.employee_id:e for e in self.employees}
        self.by_email={e.email:e for e in self.employees}
        self.by_key:dict[str,list[str]]=defaultdict(list)
        self.by_digits:dict[str,list[str]]=defaultdict(list)
        self.by_local:dict[str,list[str]]=defaultdict(list)
        for e in self.employees:
            self.by_key[_id_key(e.employee_id)].append(e.employee_id)
            self.by_digits[re.sub(r"\D","",e.employee_id)].append(e.employee_id)
            self.by_local[e.email.split("@")[0]].append(e.employee_id)
        self.id_alphabet="".join(sorted({c for e in self.employees for c in e.employee_id}))
        self.local_alphabet="".join(sorted({c for e in self.employees for c in e.email.split("@")[0]}))
        self.children:dict[str,list[str]]=defaultdict(list)
        for e in self.employees:
            if e.resolved_manager_id:
                self.children[e.resolved_manager_id].append(e.employee_id)
        #how many broken rows share each missing reference value
        self.missing_refs=Counter(_ref_value(e) for e in self.employees
                                  if e.manager_issue and e.manager_issue.code==IssueCode.MANAGER_NOT_FOUND)

    def descendants(self,employee_id:str)->set[str]:
        out:set[str]=set()
        stack=[employee_id]
        while stack:
            for c in self.children[stack.pop()]:
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    def name(self,employee_id:str)->str:
        return f"{employee_id} ({self.by_id[employee_id].employee_name})"


def _ref_value(e:Employee)->str:
    return e.manager_id or e.manager_email

def _same_dept(a:Employee,b:Employee)->bool:
    return bool(a.department) and a.department==b.department


def _not_found(e:Employee,ix:_Index,opts:SuggestOptions)->tuple[str|None,str,str]:
    mid,mem=e.manager_id,e.manager_email
    by_mid=ix.by_id.get(mid) if mid else None
    by_mem=ix.by_email.get(mem) if mem else None

    #1. one of two supplied fields is fine: the other one is the mistake
    if mid and mem and by_mem and not by_mid:
        return by_mem.employee_id,EMAIL_RESOLVES,f"manager_email {mem} belongs to {ix.name(by_mem.employee_id)}; manager_id {mid!r} matches nobody"
    if mid and mem and by_mid and not by_mem:
        return by_mid.employee_id,ID_RESOLVES,f"manager_id matches {ix.name(by_mid.employee_id)}; manager_email {mem} matches nobody"

    #2. exact match once formatting is ignored
    if mid:
        key=_id_key(mid)
        matches=ix.by_key.get(key) or (ix.by_digits.get(key) if key.isdigit() else None) or []
        if len(matches)==1:
            return matches[0],ID_FORMAT,f"manager_id {mid!r} is {ix.name(matches[0])} written in a different format"
    if mem and "@" in mem:
        local=mem.split("@")[0]
        matches=ix.by_local.get(local,[])
        if len(matches)==1:
            return matches[0],EMAIL_DOMAIN,f"{mem} has the same mailbox name as {ix.name(matches[0])} on another domain"

    #3. several rows point at the same absent value: most likely a real person missing from the export
    shared=ix.missing_refs[_ref_value(e)]
    if opts.detect_missing_manager and shared>=2:
        return None,MISSING_MANAGER,f"{_ref_value(e)!r} is referenced by {shared} rows but is not in the file; add their row or reassign"

    #4. one-edit typos
    candidates:set[str]=set()
    if mid:
        candidates|={v for v in edits1(mid,ix.id_alphabet) if v in ix.by_id}
    if mem and "@" in mem:
        local,domain=mem.split("@",1)
        for v in edits1(local,ix.local_alphabet):
            other=ix.by_email.get(f"{v}@{domain}")
            if other:
                candidates.add(other.employee_id)
    candidates-={e.employee_id}|ix.descendants(e.employee_id) #never suggest a fix that creates a cycle
    field="manager_id" if mid else "manager_email"

    if not candidates:
        return None,NO_CANDIDATE,f"no employee is within one character of {field} {_ref_value(e)!r}"
    if len(candidates)==1:
        (only,)=candidates
        why=f"{field} {_ref_value(e)!r} is one character away from {ix.name(only)}, the only close match"
        if opts.department_signal and not _same_dept(e,ix.by_id[only]):
            return only,TYPO_OTHER_DEPT,why+f", but they are in {ix.by_id[only].department or 'no department'}"
        return only,ID_TYPO if mid else EMAIL_TYPO,why
    if opts.tiebreak:
        def fit(c:str)->tuple[bool,bool]:
            return (_same_dept(e,ix.by_id[c]),c in ix.children)
        ranked=sorted(candidates,key=fit,reverse=True)
        if fit(ranked[0])>fit(ranked[1]):
            same_dept,manages=fit(ranked[0])
            why=" and ".join(w for w,ok in [("same department",same_dept),("already manages people",manages)] if ok)
            return ranked[0],TYPO_TIEBREAK,(f"{len(candidates)} employees are one character from {_ref_value(e)!r}; "
                                           f"picked {ix.name(ranked[0])}: {why}")
    return None,AMBIGUOUS,f"{len(candidates)} employees are one character from {_ref_value(e)!r}; too close to call"

def _conflict(e:Employee,ix:_Index,opts:SuggestOptions)->tuple[str|None,str,str]:

    #manager_id and manager_email name two different real people. If the id is one edit from the
    #email owner's id, the id may be the typo. With dense ids that happens by chance too, so the
    #department decides; when it can't, abstain.

    by_mid=ix.by_id[e.manager_id]
    by_mem=ix.by_email[e.manager_email]
    keep_id=(by_mid.employee_id,CONFLICT_EMAIL_WRONG,
             f"manager_email {e.manager_email} belongs to {ix.name(by_mem.employee_id)}; "
             f"keeping {ix.name(by_mid.employee_id)} from manager_id")
    if by_mem.employee_id not in edits1(e.manager_id,ix.id_alphabet):
        return keep_id
    use_email=(by_mem.employee_id,CONFLICT_ID_TYPO,
               f"manager_id {e.manager_id} is one character from {ix.name(by_mem.employee_id)}, who owns manager_email")
    if not opts.department_signal:
        return use_email
    mem_same,mid_same=_same_dept(e,by_mem),_same_dept(e,by_mid)
    if mem_same and not mid_same:
        return use_email
    if mid_same and not mem_same:
        return keep_id
    return None,AMBIGUOUS,(f"manager_id points to {ix.name(by_mid.employee_id)}, manager_email to "
                           f"{ix.name(by_mem.employee_id)}, and either could be the typo")

def suggest_fixes(result:ImportResult,options:SuggestOptions|None=None)->list[Suggestion]:
    opts=options or SuggestOptions()
    ix=_Index(result)
    out=[]
    for e in result.accepted_employees:
        issue=e.manager_issue
        if issue is None:
            continue
        if issue.code==IssueCode.MANAGER_NOT_FOUND:
            mgr,reason,why=_not_found(e,ix,opts)
        elif issue.code==IssueCode.MANAGER_CONFLICT:
            mgr,reason,why=_conflict(e,ix,opts)
        else: #SELF_MANAGED: nothing in the row says who the real manager is
            mgr,reason,why=None,NO_CANDIDATE,"the row names the employee as their own manager"
        out.append(Suggestion(e.employee_id,e.row_number,issue.code,mgr,CONFIDENCE.get(reason,0.0) if mgr else 0.0,
                              reason,why))
    return sorted(out,key=lambda s:s.row_number)
