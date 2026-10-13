"""
Basically, this file parses raw CSV bytes into normalised RawRow objects.
Uses Python's csv module to handle quoted fields, commas in fields, etc correctly.
"""


import csv
import io
from models import RawRow

REQUIRED_HEADERS={"employee_id","employee_name","email","manager_id","manager_email","department"}


class MalformedUploadError(Exception):
    pass

def parse_csv(file_bytes:bytes) -> list[RawRow]:
    #so that utf-8-sig strips a BOM if present
    #also behaves like plain utf-8 if no BOM is present
    try:
        text=file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MalformedUploadError("File is not valid UTF-8 text.")

    #plain csv.reader instead of DictReader so that:
    #1. header names can be normalised (" Employee_ID " -> "employee_id") before lookup
    #2. row_number is the line a record starts on, which stays correct when a quoted field spans lines
    reader=csv.reader(io.StringIO(text))

    try:
        header=next(reader,None)
    except csv.Error as exc:
        raise MalformedUploadError(f"Could not read header: {exc}")
    if header is None:
        raise MalformedUploadError("File appears to be empty.")

    columns=[h.strip().lower() for h in header]
    missing=REQUIRED_HEADERS-set(columns)

    if missing:
        raise MalformedUploadError(f"Missing required columns: {', '.join(sorted(missing))}")

    col_index={name:columns.index(name) for name in REQUIRED_HEADERS}

    rows=[]
    while True:
        start_line=reader.line_num+1
        try:
            values=next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise MalformedUploadError(f"Line {start_line}: {exc}")

        if not any(v.strip() for v in values):
            continue #blank line or a row of only commas

        def get(col:str)->str:
            i=col_index[col]
            return values[i].strip() if i<len(values) else ""

        rows.append(RawRow(
            row_number=start_line,
            employee_id=get("employee_id"),
            employee_name=get("employee_name"),
            email=get("email").lower(),
            manager_id=get("manager_id"),
            manager_email=get("manager_email").lower(),
            department=get("department")
        ))
    return rows
