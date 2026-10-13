"""
It orchestrates parsing, validation and hierarchy analysis in one single pipeline.
keeping it separate from the web layer, hence testing can be done directly
without any browser or HTTP client involved.
"""



from models import ImportResult, ImportError_
from parser import parse_csv, MalformedUploadError
from validator import validate_identities, resolve_managers
from graph import compute_roots, compute_manager_counts, find_cyclic_employees

MAX_UPLOAD_BYTES=5*1024*1024 #5 MB, roughly 50k rows of typical HRIS data

def run_import_preview(file_bytes:bytes)->ImportResult:
    result=ImportResult()

    if len(file_bytes)>MAX_UPLOAD_BYTES:
        result.errors.append(ImportError_(0,"",f"File is larger than the {MAX_UPLOAD_BYTES//(1024*1024)} MB limit."))
        return result

    try:
        rows=parse_csv(file_bytes)
    except MalformedUploadError as exc:
        result.errors.append(ImportError_(0,"",str(exc)))
        return result
    
    result.total_rows=len(rows)

    employees,identity_errors=validate_identities(rows)
    result.errors.extend(identity_errors)

    resolve_managers(employees)
    for e in employees:
        if e.manager_ref_error:
            result.errors.append(ImportError_(e.row_number,e.employee_id,e.manager_ref_error))

    result.accepted_employees=employees
    #sorted so the same file always renders the same way
    result.roots=sorted(compute_roots(employees),key=lambda e:e.employee_id)
    counts=compute_manager_counts(employees)
    result.manager_report_counts=dict(sorted(counts.items(),key=lambda kv:(-kv[1],kv[0])))
    result.cyclic_employee_ids=find_cyclic_employees(employees)
    result.errors.sort(key=lambda e:e.row_number)

    return result