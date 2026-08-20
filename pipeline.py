"""
It orchestrates parsing, validation and hierarchy analysis in one single pipeline.
keeping it seperate from the web layer, hence testing can be done directly done
without any browser or HTTP client involved.
"""



from models import ImportResult, ImportError_
from parser import parse_csv, MalformedUploadError
from validator import validate_identities, resolve_managers
from graph import compute_roots, compute_manager_counts, find_cyclic_employees

def run_import_preview(file_bytes:bytes)->ImportResult:
    result=ImportResult()

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
    result.roots=compute_roots(employees)
    result.manager_report_counts=compute_manager_counts(employees)
    result.cyclic_employee_ids=find_cyclic_employees(employees)

    return result