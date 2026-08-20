"""
Basically, this file parses raw CSV bytes into normalised RawRow objects.
Uses Python's csv modul to hanlde quoted fields, commas in fields, etc correctly.
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
        raise MalformedUploadError("File is not valide UTF-8 text")
    
    reader=csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise MalformedUploadError("File appears to be empoty:")
    
    header={h.strip() for h in reader.fieldnames}
    missing=REQUIRED_HEADERS-header

    if missing:
        raise MalformedUploadError(f"Missing rquired columns: {', '.join(sorted(missing))}")
    
    rows=[]
    for i,raw in enumerate(reader,start=2):
        rows.append(RawRow(
            row_number=i,
            employee_id=(raw.get("employee_id") or "").strip(),
            employee_name=(raw.get("employee_name") or "").strip(),
            email=(raw.get("email") or "").strip(),
            manager_id=(raw.get("manager_id") or "").strip(),
            manager_email=(raw.get("manager_email") or "").strip(),
            department=(raw.get("department") or "").strip()
        ))
    return rows