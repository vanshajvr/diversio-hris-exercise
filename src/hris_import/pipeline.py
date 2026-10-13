"""
It orchestrates parsing, validation and hierarchy analysis in one single pipeline.
keeping it separate from the web layer, hence testing can be done directly
without any browser or HTTP client involved.
"""


from .graph import compute_manager_counts, compute_roots, find_cyclic_employees
from .models import ImportResult, IssueCode, RowIssue, Severity
from .parser import MalformedUploadError, parse_csv
from .validator import resolve_managers, validate_identities

MAX_UPLOAD_BYTES=5*1024*1024 #5 MB, roughly 50k rows of typical HRIS data

def _file_issue(code:IssueCode,message:str)->RowIssue:
    return RowIssue(0,"",code,Severity.ERROR,message)

def run_import_preview(file_bytes:bytes)->ImportResult:
    result=ImportResult()

    if len(file_bytes)>MAX_UPLOAD_BYTES:
        message=f"File is larger than the {MAX_UPLOAD_BYTES//(1024*1024)} MB limit."
        result.issues.append(_file_issue(IssueCode.FILE_TOO_LARGE,message))
        return result

    try:
        rows=parse_csv(file_bytes)
    except MalformedUploadError as exc:
        result.issues.append(_file_issue(exc.code,str(exc)))
        return result

    result.total_rows=len(rows)

    employees,identity_errors=validate_identities(rows)
    result.issues.extend(identity_errors)

    resolve_managers(employees)
    result.issues.extend(e.manager_issue for e in employees if e.manager_issue)

    result.accepted_employees=employees
    #sorted so the same file always renders the same way
    result.roots=sorted(compute_roots(employees),key=lambda e:e.employee_id)
    counts=compute_manager_counts(employees)
    result.manager_report_counts=dict(sorted(counts.items(),key=lambda kv:(-kv[1],kv[0])))
    result.cyclic_employee_ids=find_cyclic_employees(employees)

    #cycle members are accepted, but flagged so they show up in the issue list and its counts
    for e in employees:
        if e.employee_id in result.cyclic_employee_ids:
            result.issues.append(RowIssue(e.row_number,e.employee_id,IssueCode.REPORTING_CYCLE,
                                          Severity.WARNING,"Employee is part of a reporting cycle."))

    result.issues.sort(key=lambda i:i.row_number)

    return result
