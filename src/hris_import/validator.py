"""
This file validates identity uniqueness and resolves manager references.
Two passes are needed because manager rows can appear both before and after their reports.
Hence tough to resolve managers until every email/employee_id is known.
"""


from collections import Counter

from .models import Employee, IssueCode, RawRow, RowIssue, Severity


def _reject(r:RawRow,code:IssueCode,message:str)->RowIssue:
    return RowIssue(r.row_number,r.employee_id,code,Severity.ERROR,message)

def _warn(e:Employee,code:IssueCode,message:str)->RowIssue:
    return RowIssue(e.row_number,e.employee_id,code,Severity.WARNING,message)

def validate_identities(rows: list[RawRow]) -> tuple[list[Employee], list[RowIssue]]:

    #Pass1: reject rows with missing or duplicated identity fields
    #returning the accepted employees(before manager-resolve) and identity level errors

    errors:list[RowIssue]=[]

    id_counts=Counter(r.employee_id for r in rows if r.employee_id)
    email_counts=Counter(r.email for r in rows if r.email)

    accepted:list[Employee]=[]

    for r in rows:
        if not r.employee_id:
            errors.append(_reject(r,IssueCode.MISSING_EMPLOYEE_ID,"Missing required employee_id."))
            continue
        if not r.email:
            errors.append(_reject(r,IssueCode.MISSING_EMAIL,"Missing required email."))
            continue
        if id_counts[r.employee_id]>1:
            errors.append(_reject(r,IssueCode.DUPLICATE_EMPLOYEE_ID,f"Duplicate employee_id '{r.employee_id}'."))
            continue
        if email_counts[r.email]>1:
            errors.append(_reject(r,IssueCode.DUPLICATE_EMAIL,f"Duplicate email '{r.email}'."))
            continue
        accepted.append(Employee(
            row_number=r.row_number,
            employee_id=r.employee_id,
            employee_name=r.employee_name,
            email=  r.email,
            manager_id=r.manager_id,
            manager_email=r.manager_email,
            department=r.department
        ))
    return accepted, errors

def resolve_managers(employees: list[Employee])-> None:

    #Pass2: resolve each employee's manager reference in place.
    #sets 'resolved_manager_id' on success, or 'manager_issue' on failure.
    #a failure could be 'not found', 'conflicting references' or 'self-management'.
    #An employee with a manager error is still "accepted"
    #but it produces no reporting relationship and is not treated as a root.


    by_id={e.employee_id: e for e in employees}
    by_email={e.email: e for e in employees}

    for e in employees:
        has_id=bool(e.manager_id)
        has_email=bool(e.manager_email)

        if not has_id and not has_email:
            continue #root: resolved_manager_id stays ""

        mgr_by_id=by_id.get(e.manager_id) if has_id else None
        mgr_by_email=by_email.get(e.manager_email) if has_email else None

        if has_id and has_email:
            if mgr_by_id is None or mgr_by_email is None:
                e.manager_issue=_warn(e,IssueCode.MANAGER_NOT_FOUND,"Manager reference could not be found.")
                continue
            if mgr_by_id.employee_id!=mgr_by_email.employee_id:
                e.manager_issue=_warn(e,IssueCode.MANAGER_CONFLICT,"manager_id and manager_email point to different people.")
                continue
            manager=mgr_by_id
        else:
            manager=mgr_by_id if has_id else mgr_by_email
            if manager is None:
                e.manager_issue=_warn(e,IssueCode.MANAGER_NOT_FOUND,"Manager reference could not be found.")
                continue
        if manager.employee_id==e.employee_id:
            e.manager_issue=_warn(e,IssueCode.SELF_MANAGED,"Employee cannot manage themselves.")
            continue
        e.resolved_manager_id=manager.employee_id
