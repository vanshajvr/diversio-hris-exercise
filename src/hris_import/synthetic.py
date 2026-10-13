"""
Synthetic HRIS exports with labelled corruptions.

A clean org is generated first (realistic shape: an exec team, departments owned by VPs,
managers getting rarer deeper down). Then known corruptions are injected, each one recorded
with the row it touched, the correct manager and the issue a correct validator should raise.
That ground truth is what the detection benchmark (and later the fix suggestions) is scored against.
"""


import csv
import io
import math
import random
from dataclasses import dataclass, field

from .models import IssueCode

FIRST_NAMES=["Aarav","Abena","Alex","Amara","Ana","Arjun","Ava","Bruno","Chen","Dana","Diego","Elif","Emma","Farah",
             "Felix","Grace","Hana","Ines","Isaac","Jonas","Kai","Lena","Leo","Maya","Mei","Nadia","Noah","Omar",
             "Priya","Quinn","Ravi","Rosa","Sam","Sofia","Tariq","Uma","Vera","Wei","Yara","Zoe"]
LAST_NAMES=["Adeyemi","Alvarez","Bauer","Bennett","Chen","Costa","Das","Dubois","Ellis","Fischer","Garcia","Gupta",
            "Haddad","Ito","Jensen","Kim","Kowalski","Laurent","Lopez","Mehta","Moreau","Nakamura","Nguyen","Okafor",
            "Park","Patel","Quinn","Reed","Rossi","Sato","Schmidt","Shah","Silva","Singh","Tanaka","Turner","Usman",
            "Varga","Wong","Zhang"]
DEPARTMENTS=["Engineering","Product","Sales","Customer Success","Operations","Finance","People","Marketing"]
DOMAIN="acme-corp.com"
LEGACY_DOMAIN="acme.io" #pre-rebrand domain that old exports still carry

#how a row refers to its manager, mirrors the mix seen in the sample export
REF_STYLES=[("id",0.5),("email",0.25),("both",0.25)]

#corruption kinds, in the order they are injected
DEPARTED_MANAGER="departed_manager" #manager left, their row is gone, reports still point at them
DUPLICATE_ROW="duplicate_row" #the same employee exported twice
CYCLE_EDGE="cycle_edge" #a manager is set to one of their own reports
ID_TYPO="id_typo" #one-character edit in manager_id
ID_FORMAT="id_format" #EMP-1234 written as 1234, emp1234, EMP 1234 ...
EMAIL_TYPO="email_typo" #one-character edit in the local part of manager_email
EMAIL_DOMAIN="email_domain" #manager_email on the legacy domain
EMAIL_MISMATCH="email_mismatch" #manager_id right, manager_email belongs to someone else
COSMETIC="cosmetic" #case/whitespace noise the parser must absorb, no issue expected
MISSING_DEPARTMENT="missing_department" #completeness gap, no issue expected

KINDS=[DEPARTED_MANAGER,DUPLICATE_ROW,CYCLE_EDGE,ID_TYPO,ID_FORMAT,EMAIL_TYPO,EMAIL_DOMAIN,EMAIL_MISMATCH,
       COSMETIC,MISSING_DEPARTMENT]


@dataclass
class Corruption:
    kind:str
    employee_id:str #the row that was changed
    field:str
    original:str
    corrupted:str
    true_manager_id:str|None #correct manager for this row, None when there is nothing to recover
    expected_issue:IssueCode|None #what a correct validator should raise on this row, None = nothing (or may be silent)
    collides:bool=False #the corrupted value happens to equal another real employee's id/email
    affected_ids:list[str]=field(default_factory=list) #every row expected to carry an issue because of this
    ref_style:str="" #how the row referenced its manager: "id", "email" or "both"

@dataclass
class SyntheticOrg:
    csv_bytes:bytes
    corruptions:list[Corruption]
    true_manager_of:dict[str,str|None] #clean hierarchy before corruption


def _build_tree(n:int,rng:random.Random)->list[int|None]:

    #Top-down headcount budgets: every manager owns an org of a given size and splits it among
    #4-8 direct reports with uneven random weights. Most reports get a budget of 1 (individual
    #contributors), a few get large sub-orgs. Small budgets become one flat team, so there are
    #no long single-report chains. Gives ~log(n) layers, like real orgs.

    parent:list[int|None]=[None]
    stack=[(0,n)] #(employee index, total org size including themselves)
    while stack:
        node,size=stack.pop()
        below=size-1
        if below==0:
            continue
        k=below if below<=8 else rng.randint(5,8) if node==0 else rng.randint(4,8)
        weights=[rng.expovariate(1) for _ in range(k)]
        budgets=[1]*k
        for i in rng.choices(range(k),weights,k=below-k):
            budgets[i]+=1
        #a budget of 2 would be a manager with a single report; make it two peers instead
        budgets=[x for b in budgets for x in ([1,1] if b==2 else [b])]
        for b in budgets:
            parent.append(node)
            stack.append((len(parent)-1,b))
    return parent

def _clean_rows(n:int,id_density:float,rng:random.Random)->list[dict]:
    parent=_build_tree(n,rng)

    #ids drawn from a range sized by density: 1.0 = sequential ids, 0.1 = one id in ten is in use
    span=max(n,math.ceil(n/id_density))
    ids=[f"EMP-{num}" for num in rng.sample(range(1000,1000+span),n)]

    seen_emails:dict[str,int]={}
    rows=[]
    for i in range(n):
        first,last=rng.choice(FIRST_NAMES),rng.choice(LAST_NAMES)
        local=f"{first}.{last}".lower()
        seen_emails[local]=seen_emails.get(local,0)+1
        if seen_emails[local]>1:
            local=f"{local}{seen_emails[local]}"
        rows.append({"employee_id":ids[i],"employee_name":f"{first} {last}","email":f"{local}@{DOMAIN}",
                     "manager_id":"","manager_email":"","department":"",
                     "_mgr":None if parent[i] is None else ids[parent[i]],
                     "_style":rng.choices([s for s,_ in REF_STYLES],[w for _,w in REF_STYLES])[0]})

    #the exec team each own a department, everyone below inherits it (parents always come first)
    rows[0]["department"]="Executive"
    exec_team=[i for i,p in enumerate(parent) if p==0]
    for k,i in enumerate(exec_team):
        rows[i]["department"]=DEPARTMENTS[k%len(DEPARTMENTS)]
    for i in range(1,n):
        if parent[i]!=0:
            rows[i]["department"]=rows[parent[i]]["department"]

    by_id={r["employee_id"]:r for r in rows}
    for r in rows:
        if r["_mgr"]:
            _set_ref(r,by_id[r["_mgr"]],r["_style"])
    return rows

def _set_ref(row:dict,mgr:dict,style:str)->None:
    row["manager_id"]=mgr["employee_id"] if style in ("id","both") else ""
    row["manager_email"]=mgr["email"] if style in ("email","both") else ""

def typo(value:str,rng:random.Random,alphabet:str)->str:
    #one random edit: substitute, transpose neighbours, delete or insert a character
    for _ in range(20):
        i=rng.randrange(len(value))
        op=rng.choice(["substitute","transpose","delete","insert"])
        if op=="substitute":
            out=value[:i]+rng.choice(alphabet)+value[i+1:]
        elif op=="transpose" and i<len(value)-1:
            out=value[:i]+value[i+1]+value[i]+value[i+2:]
        elif op=="delete" and len(value)>1:
            out=value[:i]+value[i+1:]
        else:
            out=value[:i]+rng.choice(alphabet)+value[i:]
        if out!=value:
            return out
    raise ValueError(f"could not produce a typo for {value!r}")

def _id_typo(employee_id:str,rng:random.Random)->str:
    prefix,num=employee_id.split("-")
    return f"{prefix}-{typo(num,rng,'0123456789')}" #real-world id typos land in the numeric part

def _id_format(employee_id:str,rng:random.Random)->str:
    prefix,num=employee_id.split("-")
    return rng.choice([num,f"{prefix.lower()}{num}",f"{prefix}{num}",f"{prefix} {num}",f"{prefix.lower()}-{num}"])


def generate_org(n:int=500,seed:int=0,corruption_rate:float=0.01,id_density:float=1.0)->SyntheticOrg:

    #corruption_rate is per kind: 0.01 on 500 rows = 5 corruptions of each kind (at least 1 when rate > 0).

    rng=random.Random(seed)
    rows=_clean_rows(n,id_density,rng)
    true_manager_of={r["employee_id"]:r["_mgr"] for r in rows}
    per_kind=max(1,round(corruption_rate*n)) if corruption_rate>0 else 0

    children:dict[str,list[str]]={}
    for r in rows:
        if r["_mgr"]:
            children.setdefault(r["_mgr"],[]).append(r["employee_id"])
    by_id={r["employee_id"]:r for r in rows}
    root_id=rows[0]["employee_id"]
    used:set[str]={root_id} #rows already touched, never corrupt one row twice
    unsafe_targets:set[str]=set() #removed or duplicated: cannot serve as a valid reference target
    corruptions:list[Corruption]=[]

    def pick(predicate)->dict|None:
        candidates=[r for r in rows if r["employee_id"] not in used and predicate(r)]
        if not candidates:
            return None
        r=rng.choice(candidates)
        used.add(r["employee_id"])
        return r

    def valid_ids()->list[str]:
        return sorted(r["employee_id"] for r in rows if r["employee_id"] not in unsafe_targets)

    if per_kind:
        #1. departed managers: drop a small team lead, their reports keep pointing at them
        for _ in range(per_kind):
            mgr=pick(lambda r:r["employee_id"] in children and len(children[r["employee_id"]])<=8
                     and not set(children[r["employee_id"]])&used)
            if mgr is None:
                break
            rows.remove(mgr)
            unsafe_targets.add(mgr["employee_id"])
            reports=children[mgr["employee_id"]]
            used.update(reports)
            for rep in reports:
                corruptions.append(Corruption(DEPARTED_MANAGER,rep,"manager_id/manager_email",mgr["employee_id"],
                                              mgr["employee_id"],None,IssueCode.MANAGER_NOT_FOUND,
                                              affected_ids=[rep]))

        #2. duplicate rows, only individual contributors so nobody's manager disappears with them
        for _ in range(per_kind):
            r=pick(lambda r:r["employee_id"] not in children)
            if r is None:
                break
            rows.insert(rng.randrange(len(rows)+1),dict(r))
            unsafe_targets.add(r["employee_id"])
            corruptions.append(Corruption(DUPLICATE_ROW,r["employee_id"],"*","","",r["_mgr"],
                                          IssueCode.DUPLICATE_EMPLOYEE_ID,affected_ids=[r["employee_id"]]))

        #3. cycles: point a manager at someone below them; the whole path becomes a loop
        for _ in range(per_kind):
            def has_clean_path(r)->bool:
                return any(c not in used for c in children.get(r["employee_id"],[]))
            x=pick(lambda r:r["_mgr"] is not None and has_clean_path(r))
            if x is None:
                break
            path=[x["employee_id"]]
            node=x["employee_id"]
            for _ in range(rng.randint(1,3)):
                options=sorted(c for c in children.get(node,[]) if c not in used and c not in path)
                if not options:
                    break
                node=rng.choice(options)
                path.append(node)
            used.update(path)
            original=x["manager_id"] or x["manager_email"]
            x["_style"]="id"
            _set_ref(x,by_id[path[-1]],"id")
            corruptions.append(Corruption(CYCLE_EDGE,x["employee_id"],"manager_id",original,path[-1],x["_mgr"],
                                          IssueCode.REPORTING_CYCLE,affected_ids=path))

        ids_in_file=set(valid_ids())
        emails_in_file={by_id[i]["email"] for i in ids_in_file}

        #4-8. single-field reference corruptions
        for _ in range(per_kind):
            r=pick(lambda r:r["_mgr"] and r["_style"] in ("id","both") and r["_mgr"] not in unsafe_targets)
            if r is None:
                break
            bad=_id_typo(r["manager_id"],rng)
            collides=bad in ids_in_file
            if not collides:
                expected=IssueCode.MANAGER_NOT_FOUND
            else: #a typo that lands on a real id is only catchable if the email disagrees
                expected=IssueCode.MANAGER_CONFLICT if r["_style"]=="both" else None
            corruptions.append(Corruption(ID_TYPO,r["employee_id"],"manager_id",r["manager_id"],bad,r["_mgr"],
                                          expected,collides,[r["employee_id"]] if expected else [],r["_style"]))
            r["manager_id"]=bad

        for _ in range(per_kind):
            r=pick(lambda r:r["_mgr"] and r["_style"] in ("id","both") and r["_mgr"] not in unsafe_targets)
            if r is None:
                break
            bad=_id_format(r["manager_id"],rng)
            corruptions.append(Corruption(ID_FORMAT,r["employee_id"],"manager_id",r["manager_id"],bad,r["_mgr"],
                                          IssueCode.MANAGER_NOT_FOUND,affected_ids=[r["employee_id"]]))
            r["manager_id"]=bad

        for _ in range(per_kind):
            r=pick(lambda r:r["_mgr"] and r["_style"]=="email" and r["_mgr"] not in unsafe_targets)
            if r is None:
                break
            local,domain=r["manager_email"].split("@")
            bad=f"{typo(local,rng,'abcdefghijklmnopqrstuvwxyz')}@{domain}"
            collides=bad in emails_in_file
            expected=None if collides else IssueCode.MANAGER_NOT_FOUND
            corruptions.append(Corruption(EMAIL_TYPO,r["employee_id"],"manager_email",r["manager_email"],bad,
                                          r["_mgr"],expected,collides,[r["employee_id"]] if expected else []))
            r["manager_email"]=bad

        for _ in range(per_kind):
            r=pick(lambda r:r["_mgr"] and r["_style"]=="email" and r["_mgr"] not in unsafe_targets)
            if r is None:
                break
            bad=r["manager_email"].replace(f"@{DOMAIN}",f"@{LEGACY_DOMAIN}")
            corruptions.append(Corruption(EMAIL_DOMAIN,r["employee_id"],"manager_email",r["manager_email"],bad,
                                          r["_mgr"],IssueCode.MANAGER_NOT_FOUND,affected_ids=[r["employee_id"]]))
            r["manager_email"]=bad

        for _ in range(per_kind):
            r=pick(lambda r:r["_mgr"] and r["_style"]=="both" and r["_mgr"] not in unsafe_targets)
            if r is None:
                break
            other=rng.choice([i for i in sorted(ids_in_file) if i!=r["_mgr"]])
            bad=by_id[other]["email"]
            corruptions.append(Corruption(EMAIL_MISMATCH,r["employee_id"],"manager_email",r["manager_email"],bad,
                                          r["_mgr"],IssueCode.MANAGER_CONFLICT,affected_ids=[r["employee_id"]]))
            r["manager_email"]=bad

        #9-10. noise that must NOT produce an issue
        for _ in range(per_kind):
            r=pick(lambda r:True)
            if r is None:
                break
            original=r["email"]
            r["email"]=f"  {r['email'].upper()} "
            r["employee_id"]=f" {r['employee_id']}"
            corruptions.append(Corruption(COSMETIC,r["employee_id"].strip(),"email/employee_id",original,r["email"],
                                          r["_mgr"],None))

        for _ in range(per_kind):
            r=pick(lambda r:True)
            if r is None:
                break
            corruptions.append(Corruption(MISSING_DEPARTMENT,r["employee_id"].strip(),"department",r["department"],
                                          "",r["_mgr"],None))
            r["department"]=""

    rng.shuffle(rows) #managers and reports in any order, like a real export
    out=io.StringIO()
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(["employee_id","employee_name","email","manager_id","manager_email","department"])
    for r in rows:
        writer.writerow([r["employee_id"],r["employee_name"],r["email"],r["manager_id"],r["manager_email"],
                         r["department"]])
    return SyntheticOrg(out.getvalue().encode("utf-8"),corruptions,true_manager_of)
