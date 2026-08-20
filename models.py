from dataclasses import dataclass, field

@dataclass
class RawRow: #A CSV row after column extraction, before normalization and validation
    row_number:int
    employee_id:str
    employee_name:str
    email:str
    manager_id:str
    manager_email:str
    department:str

@dataclass
class Employee: #A validated, normalized employee accepted for hierarchy analysis
    row_number:int
    employee_id:str
    employee_name:str
    email:str
    manager_id:str
    manager_email:str
    manager_ref_error:str="" #keep non empty if manager could not be resolved
    resolved_manager_id:str="" #keep empty if root or manager_ref_error is set

@dataclass
class ImportError_: #A row level problem preventing full acceptance or hierarchy participation.
    row_number:int
    employee_id:str
    message:str

@dataclass
class ImportResult:
    total_rows:int=0
    accepted_employees:list=field(default_factory=list) #list[Employee]
    errors:list=field(default_factory=list) #list[ImportError]
    roots:list=field(default_factory=list) #list[Employee]
    manager_report_counts:dict=field(default_factory=dict) #employee_id -> count
    cyclic_employee_ids:set=field(default_factory=set) 