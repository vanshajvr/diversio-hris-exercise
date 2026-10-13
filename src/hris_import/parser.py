"""
Basically, this file parses raw CSV bytes into normalised RawRow objects.
Uses Python's csv module to handle quoted fields, commas in fields, etc correctly.
"""


import csv
import io

from .models import IssueCode, RawRow

REQUIRED_HEADERS={"employee_id","employee_name","email","manager_id","manager_email","department"}


class MalformedUploadError(Exception):
    def __init__(self,code:IssueCode,message:str):
        super().__init__(message)
        self.code=code

def _cell(values:list[str],index:int)->str:
    return values[index].strip() if index<len(values) else "" #short rows: missing trailing cells are blank

def parse_csv(file_bytes:bytes) -> list[RawRow]:
    #so that utf-8-sig strips a BOM if present
    #also behaves like plain utf-8 if no BOM is present
    try:
        text=file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MalformedUploadError(IssueCode.FILE_NOT_UTF8,"File is not valid UTF-8 text.") from None

    #plain csv.reader instead of DictReader so that:
    #1. header names can be normalised (" Employee_ID " -> "employee_id") before lookup
    #2. row_number is the line a record starts on, which stays correct when a quoted field spans lines
    reader=csv.reader(io.StringIO(text))

    try:
        header=next(reader,None)
    except csv.Error as exc:
        raise MalformedUploadError(IssueCode.FILE_MALFORMED,f"Could not read header: {exc}") from exc
    if header is None:
        raise MalformedUploadError(IssueCode.FILE_EMPTY,"File appears to be empty.")

    columns=[h.strip().lower() for h in header]
    missing=REQUIRED_HEADERS-set(columns)

    if missing:
        raise MalformedUploadError(IssueCode.FILE_MISSING_COLUMNS,f"Missing required columns: {', '.join(sorted(missing))}")

    col_index={name:columns.index(name) for name in REQUIRED_HEADERS}

    rows=[]
    while True:
        start_line=reader.line_num+1
        try:
            values=next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise MalformedUploadError(IssueCode.FILE_MALFORMED,f"Line {start_line}: {exc}") from exc

        if not any(v.strip() for v in values):
            continue #blank line or a row of only commas

        rows.append(RawRow(
            row_number=start_line,
            employee_id=_cell(values,col_index["employee_id"]),
            employee_name=_cell(values,col_index["employee_name"]),
            email=_cell(values,col_index["email"]).lower(),
            manager_id=_cell(values,col_index["manager_id"]),
            manager_email=_cell(values,col_index["manager_email"]).lower(),
            department=_cell(values,col_index["department"])
        ))
    return rows
