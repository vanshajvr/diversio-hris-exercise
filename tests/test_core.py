import sys
import os
sys.path.insert(0,os.path.join(os.path.dirname(__file__),".."))

from pipeline import run_import_preview

HEADER="employee_id,employee_name,email,manager_id,manager_email,department\n"

def make_csv(rows:str)->bytes:
    return (HEADER+rows).encode('utf-8')

def test_simple_hierarchy_roots_and_counts():
    #A basic two-level org:
    #one root, one manager with two reports.

    csv_bytes=make_csv(
        "E1,Alice,alice@co.com,,,Eng\n"
        "E2,Bob,bob@co.com,E1,,Eng\n"
        "E3,Carol,carol@co.com,E1,,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert result.total_rows==3
    assert len(result.accepted_employees)==3
    assert [r.employee_id for r in result.roots]==["E1"]
    assert result.manager_report_counts=={"E1":2}
    assert result.cyclic_employee_ids==set()


def test_reporting_cycle_is_detected_precisely():

    # A -> B -> C -> A is a cycle.
    #also, fourth employee reporting into the cycle should not be flagged as cyclic themselves.

    csv_bytes=make_csv(
        "A,Alice,a@co.com,C,,Eng\n"
        "B,Bob,b@co.com,A,,Eng\n"
        "C,Carol,c@co.com,B,,Eng\n"
        "D,Dave,d@co.com,A,,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert result.cyclic_employee_ids=={"A","B","C"}
    assert "D" not in result.cyclic_employee_ids


def test_duplicate_employee_id_is_rejected_and_excluded_from_hierarchy():

    #both rows sharing a duplicaed ID must be invalid.
    #these must not paritcipate in manager lookup for anyone else.

    csv_bytes=make_csv(
        "E1,Alice,alice@co.com,,,Eng\n"
        "E1,Alice2,alice2@co.com,,,Eng\n"
        "E2,Bob,bob@co.com,E1,,Eng\n"
    )

    result=run_import_preview(csv_bytes)

    assert len(result.errors)==3

    accepted_ids={e.employee_id for e in result.accepted_employees}
    assert "E1" not in accepted_ids

def test_conflicting_manager_references_reported_as_error():

    #manager_id and manager_email pointing to diff people is an error
    #that employee should not appear as root or produce a reporting edge

    csv_bytes=make_csv(
        "M1,Manager One,m1@co.com,,,Eng\n"
        "M2,Manager Two,m2@co.com,,,Eng\n"
        "E1,Employee,e1@co.com,M1,m2@co.com,Eng\n" 
    )

    result=run_import_preview(csv_bytes)

    e1_errors=[e for e in result.errors if e.employee_id =="E1"]
    assert len(e1_errors)==1
    assert "different people" in e1_errors[0].message
    assert "E1" not in [r.employee_id for r in result.roots]