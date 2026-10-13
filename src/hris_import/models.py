from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR="error" #row (or whole file) rejected
    WARNING="warning" #row accepted, but its place in the hierarchy is broken


class IssueCode(StrEnum):
    #file level: the upload could not be parsed at all
    FILE_TOO_LARGE="FILE_TOO_LARGE"
    FILE_NOT_UTF8="FILE_NOT_UTF8"
    FILE_EMPTY="FILE_EMPTY"
    FILE_MISSING_COLUMNS="FILE_MISSING_COLUMNS"
    FILE_MALFORMED="FILE_MALFORMED"
    #identity: the row is rejected
    MISSING_EMPLOYEE_ID="MISSING_EMPLOYEE_ID"
    MISSING_EMAIL="MISSING_EMAIL"
    DUPLICATE_EMPLOYEE_ID="DUPLICATE_EMPLOYEE_ID"
    DUPLICATE_EMAIL="DUPLICATE_EMAIL"
    #hierarchy: the row is accepted but produces no valid reporting edge
    MANAGER_NOT_FOUND="MANAGER_NOT_FOUND"
    MANAGER_CONFLICT="MANAGER_CONFLICT"
    SELF_MANAGED="SELF_MANAGED"
    REPORTING_CYCLE="REPORTING_CYCLE"


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
class RowIssue: #A problem found in the upload. row_number is 0 for file-level issues.
    row_number:int
    employee_id:str
    code:IssueCode
    severity:Severity
    message:str

@dataclass
class Employee: #A validated, normalized employee accepted for hierarchy analysis
    row_number:int
    employee_id:str
    employee_name:str
    email:str
    manager_id:str
    manager_email:str
    department:str
    manager_issue:RowIssue|None=None #set if manager could not be resolved
    resolved_manager_id:str="" #keep empty if root or manager_issue is set

@dataclass
class ImportResult:
    total_rows:int=0
    accepted_employees:list[Employee]=field(default_factory=list)
    issues:list[RowIssue]=field(default_factory=list)
    roots:list[Employee]=field(default_factory=list)
    manager_report_counts:dict[str,int]=field(default_factory=dict) #employee_id -> count
    cyclic_employee_ids:set[str]=field(default_factory=set)

    @property
    def errors(self)->list[RowIssue]:
        return [i for i in self.issues if i.severity==Severity.ERROR]

    @property
    def warnings(self)->list[RowIssue]:
        return [i for i in self.issues if i.severity==Severity.WARNING]

    @property
    def rejected_rows(self)->int:
        return self.total_rows-len(self.accepted_employees)
