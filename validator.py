from collections import Counter
from models import RawRow, Employee, ImportError_

def validate_identities(rows: list[RawRow]) -> tuple[list[Employee], list[ImportError_]]:
    errors:list[ImportError_]=[]

    id_counts=Counter(r.employee_id for r in rows if r.employee_id)
    email_counts=Counter(r.email for r in rows if r.email)

    accepted:list[Employee]=[]

    for r in rows:
        if not r.employee_id:
            errors.append(ImportError_(r.row_number,r.employee_id, "Missing required employee_id or email."))
            continue
        if id_counts[r.employee_id]>1:
            errors.append(ImportError_(r.row_number,r.employee_id, f"Duplicae employee_id '{r.employee_id}'."))
            continue
        if email_counts[r.email]>1:
            errors.append(ImportError_(r.row_number,r.employee_id, f"Duplicare email '{r.email}'."))
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
